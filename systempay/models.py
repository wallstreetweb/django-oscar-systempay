from urllib.parse import parse_qs

from django.db import models

CURRENCIES = (
    ('36', 'AUD'),
    ('036', 'AUD'),
    ('124', 'CAD'),
    ('156', 'CNY'),
    ('208', 'DKK'),
    ('392', 'YEN'),
    ('578', 'NOK'),
    ('752', 'SEK'),
    ('756', 'CHF'),
    ('826', 'GBP'),
    ('840', 'USD'),
    ('953', 'CFP'),
    ('978', 'EUR'),
)


class SystemPayTransaction(models.Model):
    """
    Model for any transaction between the SystemPay Checkout
    server and the merchant site.

    The transaction mode attribute differentiates sent transaction
    from returning ones (notification).
    """

    MODE_SUBMIT, MODE_RETURN = ('SUBMIT', 'RETURN')
    MODE_CHOICES = (
        (MODE_SUBMIT, "SUBMIT"),
        (MODE_RETURN, "REQUEST"),
    )
    mode = models.CharField(max_length=10, choices=MODE_CHOICES)

    OPERATION_TYPE_NONE, OPERATION_TYPE_DEBIT, \
        OPERATION_TYPE_CREDIT = ('', 'DEBIT', 'CREDIT')
    OPERATION_TYPE_CHOICES = (
        (OPERATION_TYPE_NONE, ''),
        (OPERATION_TYPE_DEBIT, 'DEBIT'),
        (OPERATION_TYPE_CREDIT, 'CREDIT'),
    )
    operation_type = models.CharField(
        max_length=10, choices=OPERATION_TYPE_CHOICES, blank=True, null=True)

    # Unique identifier in the range 000000 to 899999. Integer between
    # 900000 and 999999 are reserved
    # NB: it should only be unique over the current day
    trans_id = models.CharField(max_length=6, blank=True, null=True)

    # Need to respect the format ``YYYYMMDDHHMMSS`` in UTC timezone
    trans_date = models.CharField(max_length=14, blank=True, null=True)

    order_number = models.CharField(max_length=127, blank=True, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    currency = models.CharField(max_length=8, blank=True, null=True)

    auth_result = models.CharField(max_length=2, blank=True, null=True)
    result = models.CharField(max_length=2, blank=True, null=True)

    error_message = models.TextField(max_length=512, blank=True, null=True)

    #
    # Debug information
    #
    raw_request = models.TextField(max_length=512)
    date_created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-date_created', )

    def __str__(self):
        return 'SystemPayTransaction mode: %(mode)s order_id: %(order_id)s ' \
               'trans_id: %(trans_id)s' % {'mode': self.mode.upper(),
                                           'order_id': self.order_number,
                                           'trans_id': self.trans_id, }

    def request(self):
        return self._as_table(self.context)
    request.allow_tags = True

    @staticmethod
    def _as_table(params):
        rows = []
        for k, v in sorted(params.items()):
            rows.append('<tr><th>%s</th><td>%s</td></tr>' % (k, v))
        return '<table>%s</table>' % ''.join(rows)

    def as_table(self):
        return self._as_table(self.__dict__)

    @property
    def context(self):
        return parse_qs(self.raw_request, keep_blank_values=True)

    def value(self, key):
        ctx = self.context
        return ctx[key][0] if key in ctx else None

    def is_complete(self):
        return not self.error_message and self.result == '00'

    @property
    def computed_signature(self):
        """
        Compute the signature on the fly.
        """
        params = {}
        from .facade import Facade
        f = Facade()
        for k, v in self.context.items():
            params.update({k: v[0]})
        form = f.gateway.get_return_form(**params)
        return f.gateway.compute_signature(form)

    @property
    def currency(self):
        return dict(CURRENCIES).get(self.value('vads_currency'), 'UNKNOWN')

    @property
    def reference(self):
        return self.trans_id

    def debug(self, verbose=False):
        res = self.raw_request.split('&')
        if not verbose:
            li = []
            values = ('amount', 'auth_result', 'order_id', 'trans_status',
                      'check_src', 'operation_type')
            for item in res:
                for v in values:
                    if v in item:
                        li.append(item.split('vads_')[1])
            res = li
        return sorted(res)

