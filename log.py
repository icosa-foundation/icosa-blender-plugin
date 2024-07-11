# <pep8-80 compliant>
"""Log utilities."""


# If true, debug logging is enabled.
_DEBUG_LOG_ENABLED = True


def debug(msg):
    if _DEBUG_LOG_ENABLED:
        print("D: %s" % msg)


def info(msg):
    print("I: %s" % msg)


def warn(msg):
    print("W: *** %s" % msg)


def error(msg):
    print("E: !!! ERROR !!!: %s" % msg)

