from os import path as osp
import sys
import logging


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


def grab_logger():
    log = logging.getLogger('vscope')
    log.setLevel(logging.DEBUG)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    fh = logging.FileHandler('vscope_log.txt')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    log.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(formatter)
    log.addHandler(ch)

    return log
