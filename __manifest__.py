{
    'name': 'GMAO',
    'version': '1.0',
    'depends': ['maintenance', 'mail', 'project', 'product','base', 'stock'],
    'author': 'Wiem',
    'category': 'Maintenance',
    'summary': 'GMAO intervention tickets with criticity and automatic assignment',
    'data': [
        'security/ir.model.access.csv',
        'views/maintenance_request_views.xml',
        'views/maintenance_request_menu_items.xml',
        'views\equipment_views.xml',
        'views\maintenance_plan_views.xml'
    ],
    'installable': True,
    'application': True,
}
