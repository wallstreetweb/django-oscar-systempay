from decimal import Decimal as D


def set_amount_for_systempay(amount):
    """
    Format the amount to respond to the platform needs, which is a indivisible
    version of the amount.

    c.g. if amount = $50.24
         then format_amount = 5024
    """
    return int(amount * 100)


def get_amount_from_systempay(amount):
    return D(int(amount)/100.0)


def printable_form_errors(form):
    return ' / '.join([u"%s: %s" % (f.name, '. '.join(f.errors))
                       for f in form if f.errors])
