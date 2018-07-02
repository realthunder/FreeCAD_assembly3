try:
    # try import system six module first
    from six import with_metaclass
except ImportError:
    from .six import with_metaclass

