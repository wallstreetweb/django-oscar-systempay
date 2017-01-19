# encoding: utf-8
from decimal import Decimal as D
import logging

from django.conf import settings
from django.apps import apps
from django.views import generic
from django.contrib import messages
from django.http import HttpResponse, Http404, HttpResponseRedirect, HttpResponseBadRequest
from django.core.urlresolvers import reverse
from django.utils.translation import ugettext_lazy as _

from oscar.core.loading import get_class, get_classes

from .models import SystemPayTransaction
from .facade import Facade
from .gateway import Gateway
from .exceptions import *

logger = logging.getLogger('systempay')

Basket = apps.get_model('basket', 'Basket')
Order = apps.get_model('order', 'Order')
Source = apps.get_model('payment', 'Source')
SourceType = apps.get_model('payment', 'SourceType')

PaymentDetailsView, OrderPlacementMixin, CheckoutSessionMixin = get_classes(
    'checkout.views',
    ['PaymentDetailsView', 'OrderPlacementMixin', 'CheckoutSessionMixin'])
PaymentError, UnableToTakePayment = get_classes(
    'payment.exceptions',
    ['PaymentError', 'UnableToTakePayment'])

EventHandler = get_class('order.processing', 'EventHandler')


class SecureRedirectView(CheckoutSessionMixin, generic.DetailView):
    """
    Initiate the transaction with SystemPay and redirect the user
    to SystemPay Checkout to perform the transaction.
    """
    template_name = 'systempay/secure_redirect.html'
    context_object_name = 'order'

    _order = None
    _form = None

    def get_object(self):
        if self._order is not None:
            return self._order

        order = None
        if self.request.user.is_superuser:
            if 'order_number' in self.request.GET:
                order = Order.objects.get(
                    number=self.request.GET['order_number'])
            elif 'order_id' in self.request.GET:
                order = Order.objects.get(
                    id=self.request.GET['order_id'])

        if not order:
            if 'checkout_order_id' in self.request.session:
                order = Order.objects.get(
                    pk=self.request.session['checkout_order_id'])
            else:
                raise Http404(_("No order found"))

        self._order = order
        return order

    def get_form(self):
        if self._form is not None:
            return self._form
        order = self.get_object()
        self._form = Facade().get_submit_form_populated_with_order(order)
        return self._form

    def get(self, *args, **kwargs):
        order = self.get_object()
        form = self.get_form()
        Facade().record_submit_txn(order.number, order.total_incl_tax, form)
        response = super(SecureRedirectView, self).get(*args, **kwargs)

        # Flush of all session data
        self.checkout_session.flush()

        return response

    def get_context_data(self, **kwargs):
        ctx = super(SecureRedirectView, self).get_context_data(**kwargs)
        ctx['submit_form'] = self.get_form()
        ctx['SYSTEMPAY_GATEWAY_URL'] = Gateway.URL
        return ctx


class PlaceOrderView(PaymentDetailsView):
    # template_name = 'systempay/preview.html'
    template_name = 'checkout/payment_details.html'
    template_name_preview = 'systempay/preview.html'
    # template_name_preview = 'checkout/preview.html'
    preview = True

    def post(self, request, *args, **kwargs):

        if self.preview:
            if request.POST.get('action', '') == 'place_order':
                return self.submit(**self.build_submission())
            return self.render_preview(request)

        return self.get(request, *args, **kwargs)

    def handle_payment(self, order_number, total_incl_tax, **kwargs):
        """
        Skip this step when placing the order, it'll be handle by the ipn
        received from server to server.
        Only record the allocated amount.
        """
        # Record payment source
        payment_method = self.checkout_session.payment_method()
        if payment_method is None:
            messages.error(self.request, _("Please choose a payment method."))
            return HttpResponseRedirect(reverse('checkout:payment-method'))

        source_type, is_created = SourceType.objects.get_or_create(
            code=payment_method)
        source = Source(source_type=source_type,
                        currency=kwargs.get('currency'),
                        amount_allocated=total_incl_tax,
                        amount_debited=D(0))
        self.add_payment_source(source)

    def handle_successful_order(self, order, send_confirmation_message=True):
        """
        Handle the various steps required after an order has been successfully
        placed.

        Override this view if you want to perform custom actions when an
        order is submitted.
        """
        # Send confirmation message (normally an email)
        # if send_confirmation_message:
        #     self.send_confirmation_message(order)

        # Delay the flush of all session data
        # self.checkout_session.flush()

        # Save order id in session so secure redirect page can load it
        self.request.session['checkout_order_id'] = order.id

        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('systempay:secure-redirect')


class ResponseView(generic.RedirectView):
    def get_order(self):
        # We allow superusers to force an order thank-you page for testing
        # http://localhost:8001/systempay/handle-ipn?vads_amount=330425&vads_auth_mode=FULL&vads_auth_number=3fea71&vads_auth_result=00&vads_capture_delay=0&vads_card_brand=CB&vads_card_number=497010XXXXXX0000&vads_payment_certificate=febb57ed6bb93cc6b3f14a1ccbfb3cee143c4c75&vads_ctx_mode=TEST&vads_currency=978&vads_effective_amount=330425&vads_site_id=21908992&vads_trans_date=20170117115209&vads_trans_id=427300&vads_trans_uuid=c4b5b52c439d44428aba6c489cd87a6c&vads_validation_mode=0&vads_version=V2&vads_warranty_result=YES&vads_payment_src=EC&vads_order_id=100024&vads_order_info=&vads_order_info2=&vads_order_info3=&vads_cust_email=bastien.roques1%40gmail.com&vads_cust_id=1&vads_cust_name=Bastien+Roques&vads_cust_country=&vads_contrib=&vads_user_info=&vads_cust_state=&vads_ship_to_name=jean-s%C3%A9bastien+r%C3%B4ques&vads_ship_to_street=34+rue+roucher&vads_ship_to_street2=34+rue+roucher&vads_ship_to_city=Montpellier&vads_ship_to_zip=34000&vads_ship_to_country=FR&vads_sequence_number=1&vads_contract_used=5591192&vads_trans_status=AUTHORISED&vads_expiry_month=6&vads_expiry_year=2018&vads_bank_product=F&vads_pays_ip=FR&vads_presentation_date=20170117115216&vads_effective_creation_date=20170117115216&vads_operation_type=DEBIT&vads_threeds_enrolled=Y&vads_threeds_cavv=Q2F2dkNhdnZDYXZ2Q2F2dkNhdnY%3D&vads_threeds_eci=05&vads_threeds_xid=UEZPM01tcFVxOUVpSnh0NzB4MTc%3D&vads_threeds_cavvAlgorithm=2&vads_threeds_status=Y&vads_threeds_sign_valid=1&vads_threeds_error_code=&vads_threeds_exit_status=10&vads_risk_control=&vads_result=00&vads_extra_result=&vads_card_country=FR&vads_language=&vads_action_mode=INTERACTIVE&vads_cust_address=&vads_cust_cell_phone=&vads_cust_city=&vads_payment_config=SINGLE&vads_page_action=PAYMENT&vads_cust_phone=&vads_cust_title=&vads_cust_zip=&signature=2a7786d4e622bec989278852910268bd0aabf11f

        order = None
        if self.request.user.is_superuser:
            if 'order_number' in self.request.GET:
                order = Order._default_manager.get(
                    number=self.request.GET['order_number'])
            elif 'order_id' in self.request.GET:
                order = Order._default_manager.get(
                    id=self.request.GET['orderid'])

        if not order:
            order_number = None
            if 'vads_order_id' in self.request.POST:
                order_number = self.request.POST['vads_order_id']
            elif 'vads_order_id' in self.request.GET:
                order_number = self.request.GET['vads_order_id']

            if not order_number:
                raise Http404(_("No order found"))

            try:
                order = Order._default_manager.get(number=order_number)
            except Order.DoesNotExist:
                raise Http404(_("The page requested seems outdated"))

        return order


class ReturnResponseView(ResponseView):
    def get_redirect_url(self, **kwargs):
        order = self.get_order()

        # check if the transaction exists
        txns = SystemPayTransaction.objects.filter(
            mode=SystemPayTransaction.MODE_RETURN,
            order_number=order.number
        ).order_by('-date_created')[:1]

        if not txns:
            messages.error(
                self.request,
                _("No response received from your bank for the moment. "
                  "Be patient, we'll get back to you as soon as we receive it.")
            )
        else:
            txn = txns[0]
            if txn.is_complete():  # check if the transaction has been complete
                messages.success(
                    self.request,
                    _("Your payment has been successfully validated.")
                )
            else:
                messages.error(
                    self.request,
                    _("Your payment has been rejected for the reason. You will "
                      "not be charged. Contact the support for more details.")
                )

        self.request.session['checkout_order_id'] = order.id
        return reverse('checkout:thank-you')


class CancelResponseView(ResponseView):
    def get_redirect_url(self, **kwargs):
        order = self.get_order()

        # cancel the order (to deallocate the products)
        handler = EventHandler()
        handler.handle_order_status_change(
            order, getattr(settings, 'OSCAR_STATUS_CANCELLED', None))

        # delete the order
        order.delete()

        # unfreeze the basket
        basket = Basket.objects.get(pk=order.basket_id)
        basket.thaw()

        messages.error(self.request, _("The transaction has be canceled"))
        return reverse('basket:summary')


class HandleIPN(OrderPlacementMixin, generic.View):
    def get(self, request, *args, **kwargs):
        if request.user and request.user.is_superuser:
            # Authorize admins for test purpose to copy the GET params
            #  to the POST dict
            request.POST = request.GET
            return self.post(request, *args, **kwargs)
        return HttpResponse()

    def post(self, request, *args, **kwargs):
        try:
            self.handle_ipn(request)
        except PaymentError as inst:
            return HttpResponseBadRequest(inst.message)
        return HttpResponse()

    def handle_ipn(self, request, **kwargs):
        """
        Complete payment.

        TODO: Avoid duplicate transaction.
        """
        txn = None
        try:
            txn = Facade().handle_request(request)
            order = Order.objects.get(number=txn.order_number)

            source_type, is_created = SourceType.objects.get_or_create(
                code='systempay'
            )

            if txn.operation_type == SystemPayTransaction.OPERATION_TYPE_DEBIT:
                source = Source(source_type=source_type,
                                currency=txn.currency,
                                amount_allocated=D(0),
                                amount_debited=txn.amount,
                                reference=txn.reference)
                self.add_payment_source(source)

            elif txn.operation_type == SystemPayTransaction.OPERATION_TYPE_CREDIT:
                source = Source(source_type=source_type,
                                currency=txn.currency,
                                amount_allocated=D(0),
                                amount_refunded=txn.amount,
                                reference=txn.reference)
                self.add_payment_source(source)

            else:

                raise PaymentError(
                    _("Unknown operation type '%(operation_type)s'")
                    % {'operation_type': txn.operation_type})

            self.save_payment_details(order)

        except SystemPayError as inst:
            raise inst
        except Order.DoesNotExist:
            logger.error(_("Unable to retrieve Order #%(order_number)s")
                         % {'order_number': txn.order_number})
