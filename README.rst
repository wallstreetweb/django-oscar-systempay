How to use
==========

Install
-------
Install from the github repository.

    ``pip install git+https://github.com/bastien34/django-oscar-systempay.git``

Config
------

To integrate systempay to your oscar project, you need to overwrite the root app
in order to include the bench of urls used for systempay.

`Override the root app <http://django-oscar.readthedocs.io/en/releases-1.3/howto/how_to_change_a_url.html?highlight=urls#changing-the-root-app>`_


**Settings `INSTALLED_APPS` and `context_processors`**

Start by adding `systempay` to your `INSTALLED_APPS` settings:

.. code:: python

        INSTALLED_APPS = (
            ...,
            'systempay',
        )

Systempay need a context processor to load the bank URL page as well. So in
`TEMPLATES` add the systempay context processor:

.. code:: python

    'systempay.context_processors.gateway'


**Create a app file in your project as following as following:**


.. code:: python

    # myproject/app.py
    from oscar.app import Shop as CoreShop
    from oscar.core.loading import get_class


    class Shop(CoreShop):

        systempay_app = get_class('systempay.app', 'application')

        def get_urls(self):
            urls = super().get_urls()

            urls += [
                url(r'^systempay/', include(self.systempay_app.urls)),
            ]
            return urls

    application = Shop()


**Link your root urls file to the new application**

.. code:: python

    # config/urls.py
    (...)
    from materielfroid.app import application


    urlpatterns = [
        ...
        url(r'', include(application.urls)),
        ]



