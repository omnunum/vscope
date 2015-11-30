import requests as rq
from requests.status_codes import codes
from bs4 import BeautifulSoup as bs
from tqdm import tqdm

import re
import json
from collections import defaultdict, OrderedDict
from os import path as osp
import os

from pprint import pprint as pp


class Image:
    top_level_attributes = (
        'upload_date',
        'is_featured',
        'height',
        'width',
        'description',
        'tags',
        'preset',
        'permalink',
        'responsive_url',
        'image_meta',
        '_id',
        'is_video',
        'grid_name',
        'perma_subdomain',
        'site_id'
    )
    supplementary_attributes_to_flatten = {
        'iso': ('image_meta', 'ios'),
        'phone_model': ('image_meta', 'model'),
        'phone_make': ('image_meta', 'make'),
        'preset': ('preset', 'key'),
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

        for param, value in self.details.iteritems():
            self.__dict__[param] = value

        self._enforce_directories()

        self.cached_image_width = cached_image_width \
            if cached_image_width else self.width

        self.session = self.s = session

        if auto_download_file:
            self.download_file()

    def __repr__(self):
        return json.dumps(self.details)

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

    def download_file(self):
        link = 'http://{}?w={}'.format(
            self.responsive_url, self.cached_image_width
        )
        local_filename = 'images/{}/{}-{}.jpg'.format(
            self.perma_subdomain, self._id, self.cached_image_width
        )

        if not osp.isfile(local_filename):
            r = self.s.get(link, stream=True)

            if r.status_code == codes.all_good:
                with open(local_filename, 'wb') as f:
                    r.raw.decode_content = True
                    for chunk in r.iter_content(2048):
                        f.write(chunk)


class Grid:
    def __init__(self, url='slowed.vsco.co', user_id=None):
        self.subdomain = self._strip_away_url_elements(url)
        self._enforce_directories()

        self.session = self.s = rq.Session()

        self.user_id = self._grab_user_id_of_owner() \
            if not user_id else user_id
        gen_images_300_px_wide = self._generate_images(cached_image_width=300)
        self.images = [image for image in gen_images_300_px_wide]

    def _enforce_directories(self):
        path = 'meta/{}/'.format(self.subdomain)
        if not osp.isdir(path):
            os.makedirs(path)

    def _strip_away_url_elements(self, url):
        subdomain_searcher = '(https?:\/\/)?(?P<subdomain>\w+)\.vsco\.co'
        matched = re.search(subdomain_searcher, url)
        if matched:
            return matched.group('subdomain')
        else:
            return url

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
        user_id = re.search(matcher, user_app_url).group('user_id')

        return user_id

    def _grab_metadata(self):
        media_url_formatter = lambda username, token, uid, size: \
            'https://{}.vsco.co/ajxp/{}/2.0/medias?site_id={}&page=1&size={}'\
            .format(username, token, uid, size)
        media_url_formatter__user = lambda size: \
            media_url_formatter(
                self.subdomain, self.access_token,
                self.user_id, size
            )

        media_meta_url = media_url_formatter__user(1)
        media_meta = mm = self._grab_json(media_meta_url)
        media_meta_all = media_meta['media']

        mm_remaining_count = mm['total'] - mm['size']
        if mm_remaining_count > 0:
            mm_remaining_url = media_url_formatter__user(mm_remaining_count)
            mm_remaining = self._grab_json(mm_remaining_url)
            media_meta_all.extend(mm_remaining['media'])

        return media_meta_all

    def _generate_images(self, cached_image_width=None):
        for meta in tqdm(self._grab_metadata()):
            yield Image(meta, self.s, cached_image_width=cached_image_width)

    def _cache_image_metadata(self):
        metadata = [i.details_full for i in self.images]
        filename = '{}_{}.json'.format(self.subdomain, self.user_id)
        with open(filename, 'w') as f:
            json.dump(metadata, f, indent=4)

    @property
    def grid_url(self):
        url_base = 'https://{}.vsco.co/grid/1'
        return url_base.format(self.subdomain)

    @property
    def access_token(self):
        assert 'vs' in self.s.cookies
        return self.s.cookies['vs']

    @property
    def size(self):
        return len(self.images)

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
        items_sorted = sorted(items, key=lambda t: t[1], reverse=(not ascending))
        ordered = OrderedDict(items_sorted)

        return ordered


class Analyzer:
    def __init__(self, grid, *args, **kwargs):
        pass

if '__main__' in __name__:
    grid = Grid(url='luciomx')
    histo = grid.histogram_attribute('preset')
    pp(histo, indent=4)
    for k, v in histo.items():
        print '{}: {}'.format(k, v)
