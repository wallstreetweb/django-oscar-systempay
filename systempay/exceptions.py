class SystemPayError(Exception):
    pass


class SystemPayFormNotValid(SystemPayError):
    pass


class SystemPayResultError(SystemPayError):
    vads_result = {
        '02': 'Le marchand doit contacter la banque du porteur. Déprécié.',
        '05': 'Action refusée.',
        '17': "Annulation de l'acheteur",
        '30': "Erreur de format de la requête. A mettre en rapport avec la "
              "valorisation du champ vads_extra_result.",
        '96': "Erreur technique.",
        }

    def __init__(self, code):
        self.code = code
        message = "vads_result error: '%s - %s'" % (
            self.code,
            self.vads_result.get(code, '<unknown>'))
        Exception.__init__(self, message)
