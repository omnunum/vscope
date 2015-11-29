import requests as rq
from requests.status_codes import codes
from bs4 import BeautifulSoup as bs
from tqdm import *

import re
import json
from os import path as osp
import os

from pprint import pprint as pp


class Image:
    parameters = (
        'upload_date', 'is_featured', 'height', 'width',
        'description', 'tags', 'preset', 'permalink',
        'responsive_url', 'image_meta', '_id', 'is_video',
        'grid_name', 'perma_subdomain', 'site_id'
    )

    def __init__(self, details, session, cached_image_width=None, auto_download_file=True):
        self.full_details = details
        self.details = {}
        for p in self.parameters:
            self.__dict__[p] = details.get(p, None)
            self.details[p] = details.get(p, None)
        self._enforce_directories()

        self.cached_image_width = cached_image_width \
            if cached_image_width else self.width

        self.session = self.s = session

        if auto_download_file:
            self.download_file()

    def __repr__(self):
        return json.dumps(self.details)

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
    def __init__(self, subdomain='slowed', user_id=None):
        self.subdomain = self._strip_away_url(subdomain)
        self._enforce_directories()

        self.session = self.s = rq.Session()

        self.user_id = self._grab_user_id_of_owner() \
            if not user_id else user_id

        self.images = [image for image in self._generate_images(cached_image_width=300)]

    def _enforce_directories(self):
        path = 'meta/{}/'.format(self.subdomain)
        if not osp.isdir(path):
            os.makedirs(path)

    def _strip_away_url(self, url):
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

    def grid_page_url(self, page):
        return self.grid_url.replace('1', str(page))


if '__main__' in __name__:
    grid = Grid(subdomain='luciomx')
