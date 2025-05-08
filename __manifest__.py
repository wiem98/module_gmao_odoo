{
    'name': 'GMAO',
    'version': '1.0',
    'depends': ['maintenance', 'mail', 'project', 'product','base', 'stock'],
    'sequence': 10,
    'author': 'Wiem',
    'category': 'Maintenance',
    'summary': 'GMAO intervention tickets with criticity and automatic assignment',
    'data': [
        'data/bt_stage_data.xml', 
        'data/bt_cron.xml',
        'views/bt_views.xml',
        'report/bt_report.xml',
        'security/ir.model.access.csv',
        'views/maintenance_request_views.xml',
        'views/maintenance_request_menu_items.xml',
        'views/equipment_views.xml',
        'views/maintenance_plan_views.xml'
    ],
    'installable': True,
    'application': True,
}
