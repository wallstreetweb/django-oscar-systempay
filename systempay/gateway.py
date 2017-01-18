import re
import datetime
import logging
from hashlib import sha1

from django.utils.translation import ugettext_lazy as _
from django.conf import settings
from django.core.urlresolvers import reverse
from django.contrib.sites.models import Site

from .forms import SystemPaySubmitForm, SystemPayReturnForm
from .utils import format_amount

logger = logging.getLogger('systempay')


def build_absolute_uri(location):
    """
    Require use of SSL on production mode.
    """
    scheme = "https"
    if settings.DEBUG:
        scheme = "http"
    return '%s://%s%s' % (scheme, Site.objects.get_current().domain, location)


class Gateway(object):
    """
    Gateway to make a fine API to interface with the SystemPay gateway
    of Cyberplus.
    """

    URL = "https://paiement.systempay.fr/vads-payment/"

    def __init__(self, sandbox_mode, site_id, certificate, action_mode,
                 version='V2', notify_user_by_email=False,
                 post_on_customer_return=False, custom_contracts=None):

        if not sandbox_mode:
            context_mode = 'PRODUCTION'
        else:
            context_mode = 'TEST'
        self._context_mode = context_mode

        if not re.match(r'^\d{8}$', str(site_id)):
            raise RuntimeError("Config `site_id` must contain exactly 8 digits,"
                               " and is not : '%s'" % site_id)
        self._site_id = site_id

        if action_mode not in ('INTERACTIVE', 'SILENT'):
            raise RuntimeError("Config `action_mode`='%s' is not supported by "
                               "the current version" % action_mode)
        self._action_mode = action_mode

        self._certificate = certificate
        self._version = version

        # optional params (impact the required params)
        self._notify_user_by_email = notify_user_by_email
        self._post_on_customer_return = post_on_customer_return
        self._custom_contracts = custom_contracts

    def compute_signature(self, form):
        """
        Compute the signature according to the doc.
        """
        params = form.values_for_signature(form.data)
        sign = '+'.join(params) + '+' + self._certificate
        return sha1(sign.encode(encoding='utf8')).hexdigest()

    def is_signature_valid(self, form):
        if form.is_valid():
            signature = self.compute_signature(form)
            return signature == form.cleaned_data['signature']

    def sign(self, form):
        form.data['signature'] = self.compute_signature(form)

    def get_trans_date(self):
        return datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')

    def get_trans_id(self):
        """
        Range allowed is between 000000 and 899999.
        So if we assume that there is only one transaction per sec, that
        covers 86400 unique transactions. And to decrease the probability
        of a collision between two customers in the very same second we
        can use the first digit of the microsecond.

        It's not completely bulletproof, two persons might confirm their order
        in the same time, same second and the same microsecond.
        """
        n = datetime.datetime.utcnow()
        return "%06d" % (n.hour*36000 + n.minute*600 + n.second*10 + n.microsecond/10000)

    def get_submit_form(self, amount, **kwargs):
        """
        Pre-populate the submit form with the data

        :amount: decimal or float amount value of the order
        :kwargs: additional data, check the fields of the `SystemPaySubmitForm`
         class to see all possible values.
        """
        data = {}
        data.update(kwargs)

        # required values
        data['vads_action_mode'] = self._action_mode 
        data['vads_amount'] = format_amount(amount)
        data['vads_currency'] = kwargs.get('vads_currency', '978')  # 978 stands
        # for EURO (ISO 639-1)
        data['vads_ctx_mode'] = self._context_mode
        data['vads_page_action'] = 'PAYMENT'
        data['vads_payment_config'] = kwargs.get('vads_payment_config', 'SINGLE')
        data['vads_site_id'] = self._site_id
        data['vads_trans_date'] = self.get_trans_date()
        data['vads_trans_id'] = self.get_trans_id()
        data['vads_validation_mode'] = kwargs.get('vads_validation_mode', '')
        data['vads_version'] = self._version

        # requirement depends on the configuration
        if self._notify_user_by_email:
            data['vads_cust_email'] = kwargs.get('user_email', '') 

        if self._custom_contracts:
            data['vads_contracts'] = self._custom_contracts

        data['vads_return_mode'] = 'GET'

        # Return urls (optional): if used, they have precedence on back-office
        # settings
        data['vads_url_success'] = build_absolute_uri(
            reverse('systempay:return-response')
        )
        data['vads_url_return'] = build_absolute_uri(
            reverse('systempay:return-response')
        )
        data['vads_url_cancel'] = build_absolute_uri(
            reverse('systempay:cancel-response')
        )
        data['vads_url_refused'] = build_absolute_uri(
            reverse('systempay:cancel-response')
        )

        # Automatic return
        data['vads_redirect_success_timeout'] = 5
        msg = _("You're going to be redirect to %s")
        data['vads_redirect_success_message'] = msg % settings.OSCAR_SHOP_NAME
        data['vads_redirect_error_timeout'] = 5

        return SystemPaySubmitForm(data)

    def get_return_form(self, **kwargs):
        """
        Pre-populate the return form with the current request
        """
        data = dict()
        data.update(kwargs)  # additional init data
        return SystemPayReturnForm(data)
