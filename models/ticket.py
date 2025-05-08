from odoo import models, fields, api
from datetime import timedelta, date

class MaintenanceRequest(models.Model):
    _inherit = 'maintenance.request'

    project_id = fields.Many2one('project.project', string="Project")

    criticity = fields.Selection([
        ('low', 'Faible'),
        ('medium', 'Moyenne'),
        ('high', 'Critique')
    ], string="Criticité", default="medium")

    maintenance_type = fields.Selection([
        ('preventive', 'Préventive'),
        ('corrective', 'Corrective'),
        ('curative', 'Curative'),
        ('systematic', 'Systématique'),
        ('conditional', 'Conditionnelle'),
        ('predictive', 'Prédictive'),
    ], string="Maintenance Type")

    contract_id = fields.Many2one('maintenance.plan', string="Related Contract", help="The maintenance contract related to this request.")

    request_cost = fields.Float(string="Request Cost", compute="_compute_request_cost", store=True)

    @api.depends('contract_id')
    def _compute_request_cost(self):
        for request in self:
            if request.contract_id and request.contract_id.cost:
                # Calculate cost per equipment if multiple are associated
                equipment_count = len(request.contract_id.associated_equipments) or 1
                request.request_cost = request.contract_id.cost / equipment_count
            else:
                request.request_cost = 0.0

    def compute_mtbf_from_failures(self):
        for request in self:
            if request.equipment_id:
                request.equipment_id.compute_mtbf_from_failures()

    def create_or_update_predictive_plan(self):
        for request in self:
            if request.equipment_id:
                request.equipment_id.create_or_update_predictive_plan()

    def _auto_assign(self):
        if self.criticity == 'high':
            user = self.env.ref('base.user_admin')
        else:
            user = self.env['res.users'].search([], limit=1)
        self.user_id = user

    @api.model_create_multi
    def create(self, vals_list):
        requests = super().create(vals_list)

        for request in requests:
            request._auto_assign()

            # Unified plan creation for all maintenance types
            if request.equipment_id and request.maintenance_type:
                request._create_or_update_plan()

            # Update project stage and create task
            if request.project_id:
                try:
                    ProjectStage = self.env.get('project.stage')
                    if ProjectStage:
                        intervention_proj_stage = ProjectStage.search([
                            ('name', 'ilike', 'Intervention')
                        ], limit=1)
                        if intervention_proj_stage:
                            request.project_id.stage_id = intervention_proj_stage.id

                    TaskType = self.env.get('project.task.type')
                    if TaskType:
                        task_stage = TaskType.search([
                            ('name', 'ilike', 'Intervention'),
                            ('project_ids', 'in', request.project_id.id)
                        ], limit=1)
                    else:
                        task_stage = False

                    self.env['project.task'].create({
                        'name': request.name,
                        'project_id': request.project_id.id,
                        'maintenance_request_id': request.id,
                        'user_ids': [(6, 0, [request.user_id.id])] if request.user_id else False,
                        'stage_id': task_stage.id if task_stage else False,
                        'description': f'Automatically created for maintenance: {request.name}',
                    })

                except Exception as e:
                    request.message_post(body=f"⚠️ Project integration failed: {str(e)}")

        return requests
    def _create_or_update_plan(self):
        self.ensure_one()
        Plan = self.env['maintenance.plan']

        existing_plan = Plan.search([
            ('equipment_id', '=', self.equipment_id.id),
            ('maintenance_type', '=', self.maintenance_type)
        ], limit=1)

        interval = 30
        next_date = date.today() + timedelta(days=interval)

        values = {
            'name': f"{self.maintenance_type.capitalize()} Plan for {self.name}",
            'equipment_id': self.equipment_id.id,
            'project_id': self.project_id.id if self.project_id else False,
            'responsible_id': self.user_id.id if self.user_id else False,
            'maintenance_type': self.maintenance_type,
            'interval_number': interval,
            'interval_type': 'days',
            'next_date': next_date,
            'active': True,
        }

        if existing_plan:
            existing_plan.write(values)
        else:
            Plan.create(values)

    def open_or_create_plan(self):
        self.ensure_one()
        self._create_or_update_plan()

        plan = self.env['maintenance.plan'].search([
            ('equipment_id', '=', self.equipment_id.id),
            ('maintenance_type', '=', self.maintenance_type)
        ], limit=1)

        if plan:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Maintenance Plan',
                'res_model': 'maintenance.plan',
                'view_mode': 'form',
                'res_id': plan.id,
                'target': 'new',
            }

class MaintenanceEquipment(models.Model):
    _inherit = 'maintenance.equipment'

    equipment_type = fields.Char(string="Type")
    brand = fields.Char(string="Brand")
    model_name = fields.Char(string="Model")
    serial_number = fields.Char(string="Serial No.")
    status = fields.Selection([
        ('in_use', 'In Use'),
        ('standby', 'Standby'),
        ('out_of_order', 'Out of Order'),
        ('scrapped', 'Scrapped'),
    ], string="Status", default='in_use')
    
    consumable_line_ids = fields.One2many('equipment.consumable.line','equipment_id',string='Consumables')
    

    parent_id = fields.Many2one('maintenance.equipment', string="Parent Equipment")
    child_ids = fields.One2many('maintenance.equipment', 'parent_id', string="Sub-components")

    installation_date = fields.Date(string="Installation Date")
    scrap_date = fields.Date(string="Scrap Date")
    maintenance_cycle = fields.Text(string="Maintenance Cycle Notes")

    document_ids = fields.Many2many('ir.attachment', string="Documents")
    estimated_next_failure = fields.Date(
        string="Estimated Next Failure", compute="_compute_next_failure", store=True)
    expected_mtbf = fields.Integer(string="Expected MTBF (Days)", help="Average days between failures")
    latest_failure_date = fields.Date(string="Last Failure Date")
    @api.depends('latest_failure_date', 'effective_date', 'expected_mtbf')
    def _compute_next_failure(self):
        for eq in self:
            if eq.latest_failure_date and eq.expected_mtbf:
                eq.estimated_next_failure = eq.latest_failure_date + timedelta(days=eq.expected_mtbf)
            elif eq.effective_date and eq.expected_mtbf:
                eq.estimated_next_failure = eq.effective_date + timedelta(days=eq.expected_mtbf)
            else:
                eq.estimated_next_failure = False

    def compute_mtbf_from_failures(self):
        Maintenance = self.env['maintenance.request']
        for eq in self:
            failures = Maintenance.search([
                ('equipment_id', '=', eq.id),
                ('maintenance_type', 'in', ['corrective', 'curative', 'predictive']),
                ('request_date', '!=', False)
            ], order='request_date asc')

            if len(failures) >= 2:
                intervals = [
                    (failures[i].request_date - failures[i-1].request_date).days
                    for i in range(1, len(failures))
                ]
                eq.expected_mtbf = sum(intervals) // len(intervals)
                eq.latest_failure_date = failures[-1].request_date
    def create_or_update_predictive_plan(self):
        MaintenancePlan = self.env['maintenance.plan']
        for eq in self:
            if not eq.expected_mtbf or not eq.latest_failure_date:
                continue
            
            plan = MaintenancePlan.search([
                ('equipment_id', '=', eq.id),
                ('maintenance_type', '=', 'predictive')
            ], limit=1)

            values = {
                'name': f"Predictive Plan for {eq.name}",
                'equipment_id': eq.id,
                'maintenance_type': 'predictive',
                'interval_number': eq.expected_mtbf,
                'interval_type': 'days',
                'next_date': eq.latest_failure_date + timedelta(days=eq.expected_mtbf),
                'active': True,
            }

            if plan:
                plan.write(values)
            else:
                MaintenancePlan.create(values)

class ProjectTask(models.Model):
    _inherit = 'project.task'

    maintenance_request_id = fields.Many2one('maintenance.request', string="Maintenance Request")
