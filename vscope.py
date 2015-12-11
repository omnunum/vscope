from collections import defaultdict, OrderedDict
from os import path as osp
from Queue import Queue
import re
import json
import os
import math

import argparse
import requests as rq
from requests.status_codes import codes
from bs4 import BeautifulSoup as bs
from tqdm import tqdm
from skimage import color
from skimage import io

from shared import ap, grab_logger
from threads import ThreadJSONWriter, ThreadMetadataRequest
from analyzer import Analyzer

log = grab_logger()


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
            log.debug('couldn\'t get the user_id out of: {}'
                      .format(user_app_url))

    def _grab_token(self):
        soup = self._grab_html_soup(self.vsco_grid_url)
        soup_meta = soup.find_all('meta', property='og:image')
        tokenized_url = soup_meta[0].get('content', None)

        matcher = 'https://im.vsco.co/\d/[0-9a-fA-F]*/(?P<token>[0-9a-fA-F]*)/'
        match = re.search(matcher, tokenized_url)

        if match:
            return match.group('token')
        else:
            log.debug('couldn\'t get the token out of: {}'
                      .format(tokenized_url))

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
        log.debug('grabbing json response from: {}'.format(media_meta_url))

        media_meta = self._grab_json(media_meta_url)
        mm_remaining_count = media_meta['total'] - media_meta['size']

        urls = []
        if mm_remaining_count > 0:
            if not page_limit:
                page_limit = int(math.ceil(mm_remaining_count / 1000))
            for page in range(1, page_limit):
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

    @property
    def paginated_media_urls(self):
        return self._media_urls()

    def grid_page_url(self, page):
        return self.grid_url.replace('/1', '/{}'.format(page))

    def grab_attribute_from_all_images(self, attribute):
        values = {}
        for image in self.images:
            attribute_value = image.details.get(attribute, None)
            if attribute_value is not None:
                values[image._id] = attribute_value
        return values

    def attribute_freq(self,
                       attribute,
                       proportional_values=False,
                       ascending=False
                       ):
        histogram = defaultdict(int)
        attributes = self.grab_attribute_from_all_images(attribute)
        for v in attributes.values():
            histogram[v] += 1

        if proportional_values:
            total = len(attributes)
            prop = lambda v: (v / float(total))
            histogram = {k: prop(v) for k, v in histogram.iteritems()}

        items = histogram.items()
        items_sorted = sorted(
            items,
            key=lambda t: t[1],
            reverse=(not ascending)
        )
        ordered = OrderedDict(items_sorted)

        return ordered

    def download_metadata(self, n_threads=5):
        grid_metadata_filename = '{}.json'.format(self.subdomain)
        grid_metadata_filepath = ap(osp.join('meta', grid_metadata_filename))

        web_request_queue = Queue()
        json_serialization_queue = Queue()

        for url in self._media_urls():
            web_request_queue.put(url)

        web_thread = lambda: ThreadMetadataRequest(
            web_request_queue,
            json_serialization_queue,
            self.s
        )

        pool_size = min(len(self._media_urls()), n_threads)
        web_pool = [web_thread() for x in range(pool_size)]
        json_serializer = ThreadJSONWriter(
            json_serialization_queue,
            grid_metadata_filepath
        )

        for thread in web_pool:
            thread.setDaemon(True)
            thread.start()
        json_serializer.start()

        web_request_queue.join()
        json_serialization_queue.join()


if '__main__' in __name__:
    parser = argparse.ArgumentParser(prog='PROG')
    parser.add_argument('--subdomain',
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

    grid.download_metadata()
