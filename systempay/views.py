# encoding: utf-8
from decimal import Decimal as D
import logging

from django.conf import settings
from django.apps import apps
from django.views import generic
from django.contrib import messages
from django.http import (HttpResponse, Http404, HttpResponseRedirect,
                         HttpResponseBadRequest)
from django.core.urlresolvers import reverse
from django.utils.translation import ugettext_lazy as _

from oscar.core.loading import get_class, get_classes

from .models import SystemPayTransaction
from .facade import Facade
from .gateway import Gateway
from .exceptions import SystemPayError

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


class RedirectView(CheckoutSessionMixin, generic.RedirectView):

    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        try:
            pass
        except:
            pass


class SecureRedirectView(CheckoutSessionMixin, generic.DetailView):
    """
    Simple Redirect Page initiating the transaction throughout
    a fulfilled form of the payment order send to the SystemPay
    checkout.
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
        Facade().save_submit_txn(order.number, order.total_incl_tax, form)
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
    template_name = 'checkout/payment_details.html'
    template_name_preview = 'systempay/preview.html'
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
        """
        pass

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

        order = None
        if self.request.user.is_superuser:
            if 'order_number' in self.request.GET:
                order = Order.objects.get(
                    number=self.request.GET['order_number'])
            elif 'order_id' in self.request.GET:
                order = Order.objects.get(
                    id=self.request.GET['order_id'])

        if not order:
            order_number = None
            if 'vads_order_id' in self.request.POST:
                order_number = self.request.POST['vads_order_id']
            elif 'vads_order_id' in self.request.GET:
                order_number = self.request.GET['vads_order_id']

            if not order_number:
                raise Http404(_("No order found"))

            try:
                order = Order.objects.get(number=order_number)
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
                _("No response received from your bank. Be patient, we'll get"
                  " back to you as soon as we receive it.")
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
                    _("Your payment has been rejected. You will not be "
                      "charged. Contact support for more details.")
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


class IpnView(OrderPlacementMixin, generic.View):
    """
    View to receive the Instant Payment Notification from the SystemPay
    checkout. Unfortunately, SystemPay doesn't provide a full services of
    batch. eg. no notification are sent for CAPTURED payment. To follow
    payment status, you must check web services instead.
    """
    # AUTHORISED = 'AUTHORISED'
    # CAPTURED = 'CAPTURED'

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
        """

        # TODO: SystemPay transaction should be linked to a Source as FK
        # TODO: Facade shouldn't be used like this
        # TODO: Check when order creation occurs
        # TODO: Avoid duplicate transaction / source / payment event

        try:
            txn = Facade().set_txn(request)
        except SystemPayError:
            raise SystemPayError('Something went wrong with transaction.')

        try:
            order = Order.objects.get(number=txn.order_number)
        except Order.DoesNotExist:
            msg = "Unable to retrieve Order #%s" % txn.order_number
            logger.error(msg)

        source_type, _ = SourceType.objects.get_or_create(name='systempay')
        trans_status = txn.value('vads_trans_status')
        payment_event = '%s-%s' % (txn.operation_type, trans_status)

        refunded = allocated = debited = D(0)

        # We force here the allocated amount to be captured since SystemPay
        # doesn't send any notification on a capture event
        # (authorised = captured)
        if txn.operation_type == SystemPayTransaction.OPERATION_TYPE_DEBIT:
            # if self.AUTHORISED in trans_status:
                # allocated = txn.amount
            # elif self.CAPTURED in trans_status:
            #     debited = txn.amount
            debited = txn.amount
        elif txn.operation_type == SystemPayTransaction.OPERATION_TYPE_CREDIT:
            # if self.AUTHORISED in trans_status:
            #     allocated = txn.amount
            # elif self.CAPTURED in trans_status:
            #     refunded = txn.amount
            refunded = txn.amount
        else:
            raise PaymentError(
                _("Unknown operation type '%(operation_type)s'")
                % {'operation_type': txn.operation_type})

        source = Source(source_type=source_type,
                        currency=txn.currency,
                        amount_allocated=allocated,
                        amount_debited=debited,
                        amount_refunded=refunded,
                        reference=txn.reference)

        self.add_payment_source(source)
        self.add_payment_event(payment_event,
                               txn.amount, reference=txn.reference)
        self.save_payment_details(order)

