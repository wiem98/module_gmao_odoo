from odoo import models, fields, api
from datetime import timedelta, date, datetime
from dateutil.relativedelta import relativedelta

class MaintenancePlan(models.Model):
    _name = 'maintenance.plan'
    _description = 'Maintenance Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(required=True)
    equipment_id = fields.Many2one('maintenance.equipment', string="Equipment", required=True)
    maintenance_type = fields.Selection([
        ('preventive', 'Préventive'),
        ('corrective', 'Corrective'),
        ('curative', 'Curative'),
        ('systematic', 'Systématique'),
        ('conditional', 'Conditionnelle'),
        ('predictive', 'Prédictive'),
    ], required=True)
    interval_number = fields.Integer(string="Repeat Every", required=True, default=30)
    interval_type = fields.Selection([
        ('days', 'Days'),
        ('weeks', 'Weeks'),
        ('months', 'Months')
    ], default='days', required=True)
    next_date = fields.Date(string="Next Scheduled Date", required=True, default=fields.Date.today)
    project_id = fields.Many2one('project.project', string="Project")
    responsible_id = fields.Many2one('res.users', string="Technician")
    active = fields.Boolean(default=True)


    mtbf_days = fields.Integer(string="MTBF (Days)")
    expected_failure_date = fields.Date(string="Expected Failure Date")
    prediction_source = fields.Char(string="Prediction Source")

    color = fields.Integer(string="Color Index", default=0)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled')
    ], string="Status", default='draft', tracking=True)
    date_category = fields.Selection([
        ('today', 'Today'),
        ('this_week', 'This Week'),
        ('this_month', 'This Month'),
        ('later', 'Later'),
    ], string="Date Category", compute="_compute_date_category", store=True)
    
    @api.depends('next_date')
    def _compute_date_category(self):
        for plan in self:
            if plan.next_date:
                today = date.today()
                if plan.next_date == today:
                    plan.date_category = 'today'
                elif plan.next_date <= today + timedelta(days=7):
                    plan.date_category = 'this_week'
                elif plan.next_date <= today + timedelta(days=30):
                    plan.date_category = 'this_month'
                else:
                    plan.date_category = 'later'
            else:
                plan.date_category = 'later'
    @api.depends('interval_number', 'interval_type')
    def _compute_next_date(self):
        for plan in self:
            if plan.interval_type == 'days':
                plan.next_date += timedelta(days=plan.interval_number)
            elif plan.interval_type == 'weeks':
                plan.next_date += timedelta(weeks=plan.interval_number)
            elif plan.interval_type == 'months':
                plan.next_date = plan.next_date + relativedelta(months=plan.interval_number)

    def generate_maintenance_requests(self):
        today = date.today()
        plans = self.search([('next_date', '<=', today), ('active', '=', True)])
        for plan in plans:
            self.env['maintenance.request'].create({
                'name': f"{plan.name} ({fields.Date.today()})",
                'equipment_id': plan.equipment_id.id,
                'maintenance_type': plan.maintenance_type,
                'project_id': plan.project_id.id,
                'user_id': plan.responsible_id.id if plan.responsible_id else False,
                'request_date': fields.Date.today(),
                'plan_id': plan.id,
            })
            plan._compute_next_date()
