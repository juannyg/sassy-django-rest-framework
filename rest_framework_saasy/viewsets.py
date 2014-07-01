import importlib
import logging
import traceback
from django.http import Http404
from django.utils.decorators import classonlymethod
from functools import update_wrapper
from rest_framework_saasy.settings import CLIENT_MODEL, CLIENT_MODULE_PATH

logger = logging.getLogger(__name__)


class ViewSetMixin(object):
    """@see rest_framework.viewsets.ViewSetMixin

    As rest_framework states, this is where all the magic happens.
    We're adding some extra SaaS magic by checking for the client
    lookup param in the request arguments and trying to import,
    from a client specific folder, the same module & class name
    that the base ViewSet has, but simply in a different destination...
    the client's folder.
    """
    @classonlymethod
    def as_view(cls, actions=None, **initkwargs):
        """Because of the way class based views create a closure around the
        instantiated view, we need to totally reimplement `.as_view`,
        and slightly modify the view function that is created and returned.
        """
        # The suffix initkwarg is reserved for identifing the viewset type
        # eg. 'List' or 'Instance'.
        cls.suffix = None

        # sanitize keyword arguments
        for key in initkwargs:
            if key in cls.http_method_names:
                raise TypeError("You tried to pass in the %s method name as a "
                                "keyword argument to %s(). Don't do that."
                                % (key, cls.__name__))
            if not hasattr(cls, key):
                raise TypeError("%s() received an invalid keyword %r" % (
                    cls.__name__, key))

        def _retrieve_cls(saas_url_parameter):
            """SaaS magic - determine custom viewset class or default"""
            if saas_url_parameter:
                client_filter = {CLIENT_MODEL.Meta.saas_lookup_field: saas_url_parameter}
                if not CLIENT_MODEL.objects.filter(**client_filter).exists():
                    raise Exception("Client {} does not exist".format(saas_url_parameter))

                mod_packages = cls.__module__.split('.')[3:]
                cls_name = cls.__name__
                cls_path = '{}.{}.{}'.format(CLIENT_MODULE_PATH,
                                             saas_url_parameter,
                                             '.'.join(mod_packages)
                                             )

                try:
                    merchant_cls_mod = importlib.import_module(cls_path)
                    merchant_cls = getattr(merchant_cls_mod, cls_name)
                    return merchant_cls(**initkwargs)
                except ImportError:
                    pass
                except:
                    logger.error(traceback.format_exc())
                    raise Http404

            # If there's nothing special, go classic...
            return cls(**initkwargs)

        def view(request, *args, **kwargs):
            """Slightly modified rest_framework as_view magic..."""
            saas_url_parameter = kwargs.get(CLIENT_MODEL.Meta.saas_url_param)
            self = _retrieve_cls(saas_url_parameter)
            setattr(self, CLIENT_MODEL.Meta.saas_lookup_field, saas_url_parameter)

            # We also store the mapping of request methods to actions,
            # so that we can later set the action attribute.
            # eg. `self.action = 'list'` on an incoming GET request.
            self.action_map = actions

            # Bind methods to actions
            # This is the bit that's different to a standard view
            for method, action in actions.items():
                handler = getattr(self, action)
                setattr(self, method, handler)

            # Patch this in as it's otherwise only present from 1.5 onwards
            if hasattr(self, 'get') and not hasattr(self, 'head'):
                self.head = self.get

            # And continue as usual
            return self.dispatch(request, *args, **kwargs)

        # take name and docstring from class
        update_wrapper(view, cls, updated=())

        # and possible attributes set by decorators
        # like csrf_exempt from dispatch
        update_wrapper(view, cls.dispatch, assigned=())

        # We need to set these on the view function, so that breadcrumb
        # generation can pick out these bits of information from a
        # resolved URL.
        view.cls = cls
        view.suffix = initkwargs.get('suffix', None)
        return view