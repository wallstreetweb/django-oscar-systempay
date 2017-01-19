def format_amount(amount):
    """
    Format the amount to respond to the platform needs, which is a indivisible
    version of the amount.

    c.g. if amount = $50.24 
         then format_amount = 5024
    """
    return int(amount * 100)


def printable_form_errors(form):
    return ' / '.join([u"%s: %s" % (f.name, '. '.join(f.errors))
                       for f in form if f.errors])
