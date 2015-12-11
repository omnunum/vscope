from datetime import datetime as dt
from os import path as osp
from Queue import Empty
import threading
import json

from requests.status_codes import codes
import requests as rq

from shared import ap, td_format, grab_logger

log = grab_logger()


class StoppableThread(threading.Thread):
    def __init__(self):
        super(StoppableThread, self).__init__()
        self.stoprequest = threading.Event()

    def join(self, timeout=None):
        self.stoprequest.set()
        super(StoppableThread, self).join(timeout)


class ThreadMetadataRequest(threading.Thread):
    def __init__(self, queue_in, queue_out, session=None):
        self.qi = queue_in
        self.qo = queue_out
        self.s = session
        super(ThreadMetadataRequest, self).__init__()

    def run(self):
        while True:
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

                # the entries come in to us as a list of dictionaries, and we
                # need to be able to retrieve individual entries via a key,
                # so we'll promote the '_id' attribute of the entry to be the
                # lookup key
                media_dict = {}
                for entry in media_entries:
                    media_dict[entry['_id']] = entry
                self.qo.put(media_dict)
            self.qi.task_done()


class ThreadJSONWriter(StoppableThread):
    def __init__(self, queue_in, filename):
        self.filename = filename
        self.qi = queue_in
        self.file_exists = osp.isfile(filename)
        self.dumped = False
        super(ThreadJSONWriter, self).__init__()

        readable_exists = ('does indeed' if self.file_exists else 'does not')
        log.debug('Initializing ThreadJSONWriter: file {} already exist at {}'
                  .format(readable_exists, self.filename))

    def run(self):
        filemode = 'r+w' if self.file_exists else 'w'
        i = 1
        with open(ap(self.filename), filemode) as f:
            try:
                metadata_dict = json.load(f) if self.file_exists else {}
            except ValueError:
                metadata_dict = {}

            while not self.stoprequest.isSet():
                try:
                    json_chunk = self.qi.get(True, 0.5)
                except Empty:
                    continue

                metadata_dict.update(json_chunk)
                print('Updated dict with page: {}'.format(i))
                i += 1
                self.qi.task_done()

            log.info('Starting JSON dump of metadata, {} total records'
                     .format(len(metadata_dict)))

            time_before_dump = dt.now()

            json.dump(metadata_dict, f, indent=4)

            how_long_was_i_dumping = td_format(dt.now() - time_before_dump)

            log.info('Finished dump of JSON metadata at {} in {}'
                     .format(self.filename, how_long_was_i_dumping))
