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
    'depends': ['base', 'web', 'mail', 'account', 'product', 'base_geolocalize', 'payment'],

    'data': [
        'security/laundry_management_security.xml',
        'security/ir.model.access.csv',
        'data/laundry_management_data.xml',
        'data/ir_sequence_data.xml',
        'data/email_templates.xml',
        'data/recurring_cron_data.xml',
        'data/laundry_service_zone_data.xml',
        # Menu load order matters: each file below parents its menuitem(s)
        # onto a menu defined earlier in this list (app root -> Orders ->
        # Pickups -> Garments -> Contracts -> Contract Requests -> the
        # Configuration root -> everything nested under Configuration ->
        # Reporting).
        'views/laundry_order_views.xml',
        'views/laundry_pickup_request_views.xml',
        'views/laundry_garment_views.xml',
        'views/laundry_contract_views.xml',
        'views/laundry_contract_request_views.xml',
        'views/laundry_service_zone_views.xml',
        'views/service_type_views.xml',
        'views/laundry_pricelist_views.xml',
        'views/res_config_settings_views.xml',
        'views/laundry_dashboard_views.xml',
        'views/account_move_view.xml',
        'report/laundry_pricelist_report.xml',
        'report/report_laundry_pricelist_template.xml',
        'report/laundry_garment_label_report.xml',
        'report/report_garment_label_template.xml',
        'wizard/mail_compose_views.xml',
    ],

    'demo': [
        'demo/demo_data.xml',
    ],

    'installable': True,
    'auto_install': False,
    'application': True,
    'license': 'LGPL-3',
}
