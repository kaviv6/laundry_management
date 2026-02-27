{
    'name': 'Laundry Management',
    'version': '1.0',
    "category": "Industries",
    "sequence": 1,
    'summary': """Complete Laundry Service Management""",
    'description': 'This module is very useful to manage all process of laundry'
                   'service',
    'author': 'Keval Vaja',
    'maintainer': 'Keval Vaja',
    'depends': ['base', 'web', 'mail', 'account', 'product', 'base_geolocalize', 'hr'],

    'data': [
        'security/laundry_management_security.xml',
        'security/ir.model.access.csv',
        'data/laundry_management_data.xml',
        'data/ir_sequence_data.xml',
        'views/laundry_order_views.xml',
        'views/service_type_views.xml',
        'views/account_move_view.xml',
        'views/laundry_pickup_request_views.xml',
        'views/laundry_contract_views.xml',
        'views/hr_employee_views.xml',
        'wizard/mail_compose_views.xml',
    ],

    'installable': True,
    'auto_install': False,
    'application': True,
    'license': 'LGPL-3',
}
