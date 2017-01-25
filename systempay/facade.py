from urllib.parse import urlencode
import logging

from django.conf import settings
from django.http import QueryDict
from django.utils.translation import ugettext_lazy as _

from .gateway import Gateway
from .models import SystemPayTransaction
from systempay.forms import SystemPayNotificationForm
from .utils import printable_form_errors, get_amount_from_systempay
from .exceptions import SystemPayFormNotValid, SystemPayResultError


logger = logging.getLogger('systempay')


class Facade(object):
    """
    A bridge between oscar's objects and the core gateway object.
    """

    def __init__(self):
        self.gateway = Gateway(
            settings.SYSTEMPAY_SANDBOX_MODE,
            settings.SYSTEMPAY_SITE_ID,
            settings.SYSTEMPAY_CERTIFICATE,
            getattr(settings, 'SYSTEMPAY_ACTION_MODE', 'INTERACTIVE'),
        )
        self.currency = getattr(settings, 'SYSTEMPAY_CURRENCY', 978)  # 978
        # stands for EURO (ISO 639-1)

    def get_result(self, form):
        return form.data.get('vads_result')

    def get_extra_result(self, form):
        return form.data.get('vads_extra_result')

    def get_auth_result(self, form):
        return form.data.get('vads_auth_result')

    def set_submit_form(self, order, **kwargs):
        """
        Pre-populate the submit form with order data

        :order: an oscar order instance
        :kwargs: additional data, check the fields of the `SystemPaySubmitForm`
        class to see all possible values.
        """
        params = dict()

        params['vads_order_id'] = order.number

        if order.user:
            params['vads_cust_name'] = order.user.get_full_name()
            params['vads_cust_email'] = order.user.email
            params['vads_cust_id'] = order.user.pk

        if order.billing_address:
            params['vads_cust_title'] = order.billing_address.title or ""
            params['vads_cust_address'] = order.billing_address.line1 or ""
            params['vads_cust_city'] = order.billing_address.city or ""
            params['vads_cust_state'] = order.billing_address.state or ""
            params['vads_cust_zip'] = order.billing_address.postcode or ""
            params['vads_cust_country'] = order.billing_address.country.\
                iso_3166_1_a2

        if order.shipping_address:
            params['vads_ship_to_name'] = order.shipping_address.salutation
            params['vads_ship_to_street'] = order.shipping_address.line1 or ""
            params['vads_ship_to_street2'] = order.shipping_address.line2 or ""
            params['vads_ship_to_city'] = order.shipping_address.city or ""
            params['vads_ship_to_state'] = order.shipping_address.state or ""
            params['vads_ship_to_zip'] = order.shipping_address.postcode or ""
            params['vads_ship_to_country'] = order.shipping_address.country.\
                iso_3166_1_a2

        params.update(kwargs)

        form = self.gateway.get_submit_form(
            order.total_incl_tax,
            **params
        )
        self.gateway.sign(form)
        return form

    def set_txn(self, request):
        """
        Set a transaction from an Instant Payment Notification (IPN).

        :param request: request from Ipn View
        :return: SystemPayTransaction object
        """

        form = SystemPayNotificationForm(request.POST)

        # create transaction
        order_number = request.POST.get('vads_order_id')
        amount = get_amount_from_systempay(request.POST.get('vads_amount', '0'))
        txn = self.save_txn_notification(order_number, amount, request)

        if not form.is_valid():
            txn.error_message = printable_form_errors(form)
            txn.save()
            msg = _("The data received are not complete: %s. See the "
                    "transaction record #%s for more details") % (
                printable_form_errors(form),
                txn.id,
            )
            raise SystemPayFormNotValid(msg)

        if not self.gateway.is_signature_valid(form):
            txn.error_message = \
                _("Signature not valid. Get '%s' instead of '%s'") % (
                    form.cleaned_data['signature'],
                    self.gateway.compute_signature(form)
                )
            txn.save()
            raise SystemPayFormNotValid(
                _("Incorrect signature. Check SystemPayTransaction #%s "
                  "for more details") % txn.id)

        if not txn.is_complete():
            raise SystemPayResultError(txn.result)

        return txn

    def save_submit_txn(self, order_number, amount, form):
        """
        Save submitted transaction into the database.
        """
        return self.save_txn(order_number, amount, form.data,
                             SystemPayTransaction.MODE_SUBMIT)

    def save_txn_notification(self, order_number, amount, request):
        """
        Save notification transaction into the database.
        """
        return self.save_txn(order_number, amount, request.POST.copy(),
                             SystemPayTransaction.MODE_RESPONSE)

    def save_txn(self, order_number, amount, data, mode):
        """
        Save the transaction into the database, submitted or received.
        """
        # convert the QueryDict into a dict in case of POST data
        d = {}
        if isinstance(data, QueryDict):
            for k in data:
                d[k] = data.get(k)
        else:
            d.update(data)

        return SystemPayTransaction.objects.create(
            mode=mode,
            operation_type=d.get('vads_operation_type'),
            trans_id=d.get('vads_trans_id'),
            trans_date=d.get('vads_trans_date'),
            order_number=order_number,
            amount=amount,
            auth_result=d.get('vads_auth_result'),
            result=d.get('vads_result'),
            raw_request=urlencode(d)
        )
