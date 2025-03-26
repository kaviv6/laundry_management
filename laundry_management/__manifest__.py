{
    'name': 'Laundry Management',
    'version': '18.0.0.1',
    "category": "Industries",
    "sequence": 1,
    'summary': """Complete Laundry Service Management""",
    'description': 'This module is very useful to manage all process of laundry'
                   'service',
    'author': 'Keval Vaja',
    'maintainer': 'Keval Vaja',
    'depends': ['l10n_in', 'account', 'product','point_of_sale'],
    'external_dependencies': {
        'python': ['xlsxwriter'],
    },
    'data': [
        'security/laundry_management_security.xml',
        'security/ir.model.access.csv',
        'data/laundry_management_data.xml',
        'data/ir_sequenca_data.xml',
        'views/laundry_order_views.xml',
        'views/service_type_views.xml',
        'views/acount_move_view.xml',
        'wizard/mail_compose_views.xml',
        'views/pos_config_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': True,
}
