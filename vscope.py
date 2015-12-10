import requests as rq
from requests.status_codes import codes
from bs4 import BeautifulSoup as bs
from tqdm import tqdm

import re
import json
from collections import defaultdict, OrderedDict
from os import path as osp
import os
import sys

from pprint import pprint as pp
import argparse
from skimage import color
from skimage import io
from sklearn import cluster
import numpy as np
import math
from threading import Thread
import threading
from multiprocessing import Queue
from Queue import Empty


class Image:
    top_level_attributes = (
        'upload_date',
        'is_featured',
        'height',
        'width',
        'description',
        'tags',
        'permalink',
        'responsive_url',
        '_id',
        'is_video',
        'grid_name',
        'perma_subdomain',
        'site_id'
    )
    supplementary_attributes_to_flatten = {
        'iso': ('image_meta', 'ios'),
        'model': ('image_meta', 'model'),
        'make': ('image_meta', 'make'),
        'preset': ('preset', 'short_name'),
        'preset_bg_color': ('preset', 'color')
    }

    def __init__(self,
                 details,
                 session,
                 cached_image_width=None,
                 auto_download_file=True,
                 ):
        self._raw_details = details

        tvp = self.top_level_attributes
        self.details = {k: details.get(k, None) for k in tvp}
        self.details.update(self._flatten_supplementary_attributes())
        self.details['camera'] = '{} {}'.format(
            self.details['make'],
            self.details['model']
        )

        for param, value in self.details.iteritems():
            self.__dict__[param] = value
            self._add_param(param, value)

        self._enforce_directories()

        self.cached_image_width = cached_image_width \
            if cached_image_width else self.width

        self.session = self.s = session

        self.link = 'http://{}?w={}'.format(
            self.responsive_url, self.cached_image_width
        )
        self.local_filename = 'images/{}/{}-{}.jpg'.format(
            self.perma_subdomain, self._id, self.cached_image_width
        )

        if auto_download_file and not osp.isfile(self.local_filename):
            self.cache_image_file()

    def __repr__(self):
        return json.dumps(self.details)

    def _add_param(self, name, value):
        self.details[name] = value

    def _flatten_supplementary_attributes(self):
        flattened = {}
        a = self.supplementary_attributes_to_flatten
        for name, (first_lvl_key, second_lvl_key) in a.iteritems():
            if first_lvl_key in self._raw_details:
                first_level_dict = self._raw_details[first_lvl_key]
                if second_lvl_key in first_level_dict:
                    flattened[name] = first_level_dict[second_lvl_key]
                    continue
            flattened[name] = None
        return flattened

    def _enforce_directories(self):
        path = 'images/{}/'.format(self.perma_subdomain)
        if not osp.isdir(path):
            os.makedirs(path)

    @property
    def data_array_rgb(self):
        if hasattr(self, '_image_data_rgb'):
            return self._image_data_rgb

        if not osp.isfile(self.local_filename):
            self.cache_image_file()

        img = io.imread(self.local_filename)
        self._image_data_rgb = img

        return img

    @property
    def data_array_lab(self):
        return color.rgb2lab(self.data_array_rgb)

    @property
    def primary_colors(self):
        if hasattr(self, 'primary_colors'):
            return self.primary_colors

        primary_colors = Analyzer.find_primary_colors(self)
        self._add_param('primary_colors', primary_colors)

        return primary_colors

    def cache_image_file(self):
        r = self.s.get(self.link, stream=True)

        if r.status_code == codes.all_good:
            with open(self.local_filename, 'wb') as f:
                r.raw.decode_content = True
                for chunk in r.iter_content(2048):
                    f.write(chunk)


class Grid:
    vsco_grid_url = 'http://vsco.co/grid/grid/1/'
    vsco_grid_site_id = 113950

    def __init__(self, subdomain='slowed',
                 user_id=None, cached_image_width=300,
                 auto_cache_images=True
                 ):
        self.cached_image_width = cached_image_width
        self.auto_cache_images = auto_cache_images

        self.subdomain = subdomain
        self._enforce_directories()

        self.session = self.s = rq.Session()
        self.s.headers.update({
            'User-Agent': '''Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3)
                              AppleWebKit/537.75.14 (KHTML, like Gecko)
                              Version/7.0.3 Safari/7046A194A'''
        })

        if self.subdomain == 'grid':
            self.user_id = self.vsco_grid_site_id
        else:
            self.user_id = self._grab_user_id_of_owner() \
                if not user_id else user_id

    def _enforce_directories(self):
        path = 'meta/{}/'.format(self.subdomain)
        if not osp.isdir(path):
            os.makedirs(path)

    def _grab_session_response(self, url):
        return self.session.get(url)

    def _grab_html_soup(self, url):
        r = self._grab_session_response(url)

        return bs(r.text, 'html.parser')

    def _grab_json(self, url):
        r = self._grab_session_response(url)
        if r.status_code == codes.all_good:
            return r.json()
        else:
            return {}

    def _grab_user_id_of_owner(self):
        soup = self._grab_html_soup(self.grid_url)
        soup_meta = soup.find_all('meta', property='al:ios:url')
        user_app_url = soup_meta[0].get('content', None)
        matcher = 'user/(?P<user_id>\d+)/grid'
        match = re.search(matcher, user_app_url)
        if match:
            return match.group('user_id')
        else:
            print('couldn\'t get the user_id out of: {}'.format(user_app_url))

    def _grab_token(self):
        soup = self._grab_html_soup(self.vsco_grid_url)
        soup_meta = soup.find_all('meta', property='og:image')
        tokenized_url = soup_meta[0].get('content', None)
        matcher = 'https://im.vsco.co/\d/[0-9a-fA-F]*/(?P<token>[0-9a-fA-F]*)/'
        match = re.search(matcher, tokenized_url)
        if match:
            return match.group('token')
        else:
            print('couldn\'t get the token out of: {}'.format(tokenized_url))

    def _media_urls(self, page_limit=None, page_size=1000):
        media_url_formatter = lambda token, uid, page: \
            'https://vsco.co/ajxp/{}/2.0/medias?site_id={}&page={}&size={}'\
            .format(token, uid, page, page_size)
        media_url_formatter__page = lambda page: \
            media_url_formatter(
                self.access_token,
                self.user_id,
                page
            )

        media_meta_url = media_url_formatter__page(1)
        print('media_meta_url is : {}'.format(media_meta_url))
        media_meta = mm = self._grab_json(media_meta_url)
        pp(media_meta, indent=4)
        media_meta_all = media_meta['media']

        mm_remaining_count = mm['total'] - mm['size']
        if not page_limit:
            page_limit = int(math.ceil(mm_remaining_count / 1000))
        urls = []
        if mm_remaining_count > 0:
            for page in range(2, page_limit):
                urls.append(media_url_formatter__page(page))

        return urls

    def _generate_images(self):
        for meta in tqdm(self.metadata):
            yield Image(
                meta,
                self.s,
                cached_image_width=self.cached_image_width,
                auto_download_file=self.auto_cache_images
            )

    def _cache_image_metadata(self):
        metadata = [i.details_full for i in self.images]
        filename = '{}_{}.json'.format(self.subdomain, self.user_id)
        with open(filename, 'w') as f:
            json.dump(metadata, f, indent=4)

    @property
    def grid_url(self):
        url_base = 'https://vsco.co/{}/grid/1'
        return url_base.format(self.subdomain)

    @property
    def access_token(self):
        token = self.s.cookies.get('vs', domain='vsco.co', default=None)
        if not token:
            token = self._grab_token()
            self.s.cookies.set('vs', token, domain='vsco.co')
        return token

    @property
    def size(self):
        return len(self.images)

    def paginated_media_urls(self, page_limit=None):
        return self._media_urls(page_limit=page_limit)

    def grid_page_url(self, page):
        return self.grid_url.replace('1', str(page))

    def grab_attribute_from_all_images(self, attribute):
        values = {}
        for image in self.images:
            attribute_value = image.details.get(attribute, None)
            if attribute_value is not None:
                values[image._id] = attribute_value
        return values

    def histogram_attribute(self,
                            attribute,
                            proportional_values=False,
                            ascending=False
                            ):
        histogram = defaultdict(int)
        attributes = self.grab_attribute_from_all_images(attribute)
        for v in attributes.values():
            histogram[v] += 1

        if proportional_values:
            total = float(len(attributes))
            histogram = {k: (v / total) for k, v in histogram.iteritems()}

        items = histogram.items()
        items_sorted = sorted(
            items,
            key=lambda t: t[1],
            reverse=(not ascending)
        )
        ordered = OrderedDict(items_sorted)

        return ordered


class Analyzer:
    def __init__(self, grid, *args, **kwargs):
        pass

    @staticmethod
    def find_primary_colors(image, resolve_to_n_colors=20):
        k = resolve_to_n_colors
        lab = image.data_array_lab
        shape = lab.shape

        centroids, centroid_ixs, intertia = cluster.k_means(
            np.reshape(lab, (shape[0] * shape[1], shape[2])),
            k
        )

        hist = np.histogram(centroid_ixs, bins=k, range=[0, k])
        freqs = hist[0].tolist()
        bins = hist[1].astype(int).tolist()

        sorted_hist = sorted(
            zip(bins, freqs),
            key=lambda x: x[1],
            reverse=True
        )

        top_centroids_ixs = [x[0] for x in sorted_hist]
        top_colors_lab = [centroids[c] for c in top_centroids_ixs]
        lab_shaped = np.reshape(top_colors_lab, (1, k, 3))
        top_colors_rgb = (color.lab2rgb(lab_shaped) * 255).astype(int)

        return top_colors_rgb


class StoppableThread(Thread):
    def __init__(self):
        super(StoppableThread, self).__init__()
        self.stoprequest = threading.Event()

    def join(self, timeout=None):
        self.stoprequest.set()
        super(StoppableThread, self).join(timeout)


class ThreadWebRequest(StoppableThread):
    def __init__(self, queue_in, queue_out, session=None):
        self.qi = queue_in
        self.qo = queue_out
        self.s = session
        super(ThreadWebRequest, self).__init__()

    def run(self):
        while not self.stoprequest.isSet():
            try:
                url = self.qi.get(True, 0.05)
            except Empty:
                    continue
            if self.s:
                r = self.s.get(url)
            else:
                r = rq.get(url)
            if r.status_code == codes.all_good:
                json_response = r.json()
                media_entries = json_response['media']

                media_dict = {}
                for entry in media_entries:
                    media_dict[entry['_id']] = entry

                self.qo.put(media_dict)


class ThreadJSONWriter(StoppableThread):
    def __init__(self, queue_in, filename):
        self.filename = filename
        self.qi = queue_in
        self.file_exists = osp.isfile(filename)
        super(ThreadJSONWriter, self).__init__()

    def run(self):
        filemode = 'rw+' if self.file_exists else 'w'
        i = 0
        with open(self.filename, filemode) as f:
            try:
                metadata_dict = json.load(f) if self.file_exists else {}
            except ValueError:
                metadata_dict = {}

            while not self.stoprequest.isSet():
                try:
                    json_chunk = self.qi.get(True, 0.05)
                except Empty:
                    continue
                metadata_dict.update(json_chunk)
                print('Updated dict with page: {}'.format(i))
                i += 1
            json.dump(metadata_dict, f, indent=4)


def ap(path):
    """
        Gets the absolute path of the directory and appends the path to it.
    """
    return osp.join(osp.dirname(osp.abspath(sys.argv[0])), path)


if '__main__' in __name__:
    thread_pool_size = 5

    parser = argparse.ArgumentParser(prog='PROG')
    parser.add_argument('subdomain',
                        help='''Can be either the subdomain
                         or full url of anything with the subdomain in it''',
                        default='slowed'
                        )
    parser.add_argument('--hist',
                        help='''Specify an Image Parameter to bin the
                         frequencies of the different values''',
                        default='preset'
                        )
    parser.add_argument('--auto-cache',
                        help='''Automatically download and cache all images
                                 in grid''',
                        type=bool,
                        default='False'
                        )
    args = parser.parse_args()

    grid = Grid(subdomain=args.subdomain, auto_cache_images=args.auto_cache)
    grid_metadata_filename = '{}.json'.format(args.subdomain)
    grid_metadata_filepath = ap(osp.join('meta', grid_metadata_filename))

    web_request_queue = Queue()
    json_serializing_queue = Queue()

    for url in grid.paginated_media_urls():
        web_request_queue.put(url)

    web_thread = lambda: ThreadWebRequest(
        web_request_queue,
        json_serializing_queue,
        grid.session
    )

    web_pool = [web_thread() for x in range(thread_pool_size)]
    json_serializer = ThreadJSONWriter(
        json_serializing_queue,
        grid_metadata_filepath
    )

    for thread in web_pool:
        thread.start()
    json_serializer.start()

    for thread in web_pool:
        thread.join()
    json_serializer.join()
