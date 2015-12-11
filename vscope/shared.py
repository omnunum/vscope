from datetime import datetime as dt
from os import path as osp
import sys
import logging
import json


def grab_logger():
    log = logging.getLogger('vscope')

    if not log.handlers:
        log.setLevel(logging.DEBUG)

        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )

        fh = logging.FileHandler('vscope_log.txt')
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        log.addHandler(fh)

        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(formatter)
        log.addHandler(ch)

    return log


def ap(path):
    """
        Gets the absolute path of the directory and appends the path to it.
    """
    return osp.join(osp.dirname(osp.abspath(sys.argv[0])), path)


def td_format(td_object):
    seconds = int(td_object.total_seconds())
    periods = [
        ('year', 60 * 60 * 24 * 365),
        ('month', 60 * 60 * 24 * 30),
        ('day', 60 * 60 * 24),
        ('hour', 60 * 60),
        ('minute', 60),
        ('second', 1)
    ]

    strings = []
    for period_name, period_seconds in periods:
            if seconds >= period_seconds:
                period_value, seconds = divmod(seconds, period_seconds)
                if period_value == 1:
                    strings.append("%s %s" % (period_value, period_name))
                else:
                    strings.append("%s %ss" % (period_value, period_name))

    return ", ".join(strings)


def list_of_dicts_to_dict(dictionary, promote_to_key='_id'):
    media_dict = {}
    for entry in dictionary:
        if promote_to_key in entry:
            media_dict[entry[promote_to_key]] = entry
    return media_dict


def dump_json(dictionary, file_object):
    log = grab_logger()
    log.info('Starting JSON dump of metadata, {} total records'
             .format(len(dictionary)))

    time_before_dump = dt.now()

    file_object.seek(0)
    json.dump(dictionary, file_object, indent=4)

    how_long_was_i_dumping = td_format(dt.now() - time_before_dump)

    log.info('Finished dump of JSON metadata at {} in {}'
             .format(file_object.name, how_long_was_i_dumping))


def load_json(file_object):
    log = grab_logger()
    log.debug('Starting JSON load of metadata at {}'
              .format(file_object.name))

    time_before_dump = dt.now()

    dictionary = json.load(file_object)

    how_long_was_i_dumping = td_format(dt.now() - time_before_dump)

    log.info('Finished load of JSON metadata in {}'
             .format(how_long_was_i_dumping))

    return dictionary
