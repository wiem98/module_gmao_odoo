from odoo import models, fields, api
from datetime import timedelta, date, datetime
from odoo.exceptions import UserError


class MaintenanceRequest(models.Model):
    _inherit = "maintenance.request"

    project_id = fields.Many2one("project.project", string="Project")

    total_task_duration = fields.Float(
        string="Total Hours Spent",
        readonly=True,
        help="Total hours spent on related tasks when request is done"
    )

    def write(self, vals):
        res = super(MaintenanceRequest, self).write(vals)
        # Check if stage is being updated
        if 'stage_id' in vals:
            for request in self:
                # Get the current stage after write
                current_stage = request.stage_id
                # Check if the current stage is considered "Done" (by name)
                if current_stage and current_stage.name.lower() == 'done':
                    request._compute_total_task_duration()
                    task = self.env['project.task'].search([
                        ('maintenance_request_id', '=', request.id)
                    ])
                    if task.stage_id.id:
                        task.state = "1_done"
                        # Step 2: Mark activities on task as done
                        task_activities = self.env['mail.activity'].search([
                            ('res_model', '=', 'project.task'),
                            ('res_id', '=', task.id),
                        ])
                        for activity in task_activities:
                            activity.action_feedback(feedback="Auto-closed with maintenance request.")
                            
                    # Step 3: Mark activities on maintenance request as done
                    mr_activities = self.env['mail.activity'].search([
                        ('res_model', '=', 'maintenance.request'),
                        ('res_id', '=', request.id),
                    ])
                    for activity in mr_activities:
                        activity.action_feedback(feedback="Auto-closed with stage set to Done.")

        return res

    def _compute_total_task_duration(self):
        for request in self:
            # Get all tasks related to this maintenance request
            tasks = self.env['project.task'].search([
                ('maintenance_request_id', '=', request.id)
            ])
            # Sum all task hours from the check-in/check-out system
            request.total_task_duration = sum(task.total_hours_spent for task in tasks)

    criticity = fields.Selection(
        [("low", "Faible"), ("medium", "Moyenne"), ("high", "Critique")],
        string="Criticité",
        default="medium",
    )

    maintenance_type = fields.Selection(
        [
            ("preventive", "Préventive"),
            ("corrective", "Corrective"),
            ("curative", "Curative"),
            ("systematic", "Systématique"),
            ("conditional", "Conditionnelle"),
            ("predictive", "Prédictive"),
        ],
        string="Maintenance Type",
    )

    maintenance_plan_ids = fields.One2many(
        "maintenance.plan", "maintenance_request_id", string="Related Maintenance Plans"
    )

    contract_id = fields.Many2one(
        "maintenance.plan",
        string="Related Contract",
        help="The maintenance contract related to this request.",
    )

    request_cost = fields.Float(
        string="Request Cost", compute="_compute_request_cost", store=True
    )

    def _get_project_stage_in_progress(self):
        return self.env['project.project.stage'].search([('name', 'ilike', 'in progress')], limit=1)

    def _get_or_create_stage(self, name, project):
        Stage = self.env["project.task.type"]

        # Desired order mapping
        order_map = {
            "Today": 1,
            "This Week": 2,
            "This Month": 3,
            "Later": 4,
        }

        stage = Stage.search([("name", "=", name)], limit=1)

        if not stage:
            stage = Stage.create({
                "name": name,
                "sequence": order_map.get(name, 99),  # fallback to 99 if name not mapped
            })
        else:
            # Ensure stage sequence is correct
            expected_sequence = order_map.get(name)
            if expected_sequence is not None and stage.sequence != expected_sequence:
                stage.sequence = expected_sequence

        # Link to project if not already
        """ if project and project.id not in stage.project_ids.ids:
            stage.project_ids = [(4, project.id)] """

        return stage


    
    def _ensure_all_stages_exist_for_project(self, project):
        stage_names = ["Today", "This Week", "This Month", "Later"]
        for name in stage_names:
            self._get_or_create_stage(name, project)

    def _get_stage_based_on_deadline(self, deadline, project):
        today = fields.Date.context_today(self)

        # Convert deadline to a date object if it's datetime
        if isinstance(deadline, datetime):
            deadline = deadline.date()

        if not deadline:
            return self._get_or_create_stage("Later", project)
        elif deadline < today:
            return self._get_or_create_stage("Overdue", project)
        elif deadline == today:
            return self._get_or_create_stage("Today", project)
        elif deadline <= today + timedelta(days=7):
            return self._get_or_create_stage("This Week", project)
        else:
            return self._get_or_create_stage("Later", project)

    def _get_active_contract(self):
        self.ensure_one()
        Contract = self.env["maintenance.service.contract"]
        today = fields.Date.context_today(self)

        return Contract.search(
            [
                ("associated_equipments", "in", self.equipment_id.id),
                ("contract_start_date", "<=", today),
                ("contract_end_date", ">=", today),
            ],
            limit=1,
        )

    @api.depends("contract_id")
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
        if self.criticity == "high":
            user = self.env.ref("base.user_admin")
        else:
            user = self.env["res.users"].search([], limit=1)
        self.user_id = user

    @api.model_create_multi
    def create(self, vals_list):
        requests = super().create(vals_list)

        for request in requests:
            request._auto_assign()

            # Update project stage and create task
            if request.project_id:
                try:
                    deadline = request.schedule_date
                    project = request.project_id

                    # Auto-move project to "In Progress" stage if just created
                    if project.create_date and (fields.Datetime.now() - project.create_date) < timedelta(seconds=30):
                        in_progress_stage = self.env['project.project.stage'].search([('name', '=', 'In Progress')], limit=1)
                        if in_progress_stage:
                            project.stage_id = in_progress_stage.id

                    # Ensure all required stages are created and linked to the project
                    request._ensure_all_stages_exist_for_project(request.project_id)


                    # Determine the appropriate stage based on the deadline
                    task_stage = request._get_stage_based_on_deadline(deadline, project)

                    task = self.env["project.task"].create(
                        {
                            "name": request.name,
                            "project_id": project.id,
                            "stage_id": task_stage.id,
                            "maintenance_request_id": request.id,
                            "user_ids": (
                                [(6, 0, [request.user_id.id])]
                                if request.user_id
                                else False
                            ),
                            "description": f"Automatically created for maintenance: {request.name}",
                            "date_deadline": request.schedule_date,
                        }
                    )

                    # Create an activity on the created task
                    if task and request.schedule_date:
                        self.env["mail.activity"].create({
                            "res_model_id": self.env["ir.model"]._get_id("project.task"),
                            "res_id": task.id,
                            "activity_type_id": self.env.ref("mail.mail_activity_data_todo").id,
                            "summary": request.description or f"Task for maintenance: {request.name}",
                            "user_id": request.user_id.id if request.user_id else self.env.uid,
                            "date_deadline": request.schedule_date,
                        })

                except Exception as e:
                    request.message_post(body=f"⚠️ Project integration failed: {str(e)}")


            # Créer automatiquement un bon de travail
            bt_model = self.env["gmao.bt"]
            contract = request._get_active_contract()
            bt_vals = {
                "name": f"New BT for {request.name}",
                "equipment_id": request.equipment_id.id,
                "intervention_type": request.maintenance_type,
                "technician_id": (
                    request.equipment_id.technician_user_id.id
                    if request.equipment_id.technician_user_id
                    else False
                ),
                "supervisor_id": request.user_id.id,
                "description": request.description
                or f"BT généré automatiquement depuis la demande {request.name}",
                "schedule_date": fields.Date.today(),
                "priority": request.priority,
                "used_parts_ids": [
                    (
                        6,
                        0,
                        request.equipment_id.consumable_line_ids.mapped(
                            "product_id"
                        ).ids,
                    )
                ],
                "contract_id": contract.id if contract else False,
            }

            bt_record = bt_model.create(bt_vals)
            # Add Activity to the BT record
            if bt_record.technician_id and bt_record.schedule_date:
                bt_record.activity_schedule(
                    "mail.activity_data_todo",
                    summary=bt_record.description,
                    user_id=bt_record.technician_id.id,
                    date_deadline=bt_record.schedule_date,
                )

        return requests

    def _create_or_update_plan(self):
        self.ensure_one()
        Plan = self.env["maintenance.plan"]

        existing_plan = Plan.search(
            [
                ("equipment_id", "=", self.equipment_id.id),
                ("maintenance_type", "=", self.maintenance_type),
            ],
            limit=1,
        )

        interval = 30
        next_date = date.today() + timedelta(days=interval)

        values = {
            "name": f"{self.maintenance_type.capitalize()} Plan for {self.name}",
            "equipment_id": self.equipment_id.id,
            "project_id": self.project_id.id if self.project_id else False,
            "responsible_id": self.user_id.id if self.user_id else False,
            "maintenance_type": self.maintenance_type,
            "interval_number": interval,
            "interval_type": "days",
            "next_date": next_date,
            "active": True,
        }

        if existing_plan:
            existing_plan.write(values)
        else:
            Plan.create(values)

    def open_or_create_plan(self):
        self.ensure_one()

        if not self.equipment_id:
            raise UserError(
                "Please set the Equipment field before creating a Maintenance Plan."
            )

        # Search for a plan linked to *this* request
        existing_plan = self.env["maintenance.plan"].search(
            [
                ("maintenance_request_id", "=", self.id),
                ("equipment_id", "=", self.equipment_id.id),
                ("maintenance_type", "=", self.maintenance_type),
            ],
            limit=1,
        )

        values = {
            "name": f"{self.name} Plan",
            "maintenance_type": self.maintenance_type,
            "equipment_id": self.equipment_id.id,
            "project_id": self.project_id.id if self.project_id else False,
            "responsible_id": self.user_id.id if self.user_id else False,
            "active": True,
            "maintenance_request_id": self.id,
        }

        if existing_plan:
            existing_plan.write(values)
            plan = existing_plan
        else:
            plan = self.env["maintenance.plan"].create(values)

        return {
            "type": "ir.actions.act_window",
            "name": "Maintenance Plan",
            "res_model": "maintenance.plan",
            "view_mode": "form",
            "res_id": plan.id,
            "target": "new",
        }


class MaintenanceEquipment(models.Model):
    _inherit = "maintenance.equipment"

    equipment_type = fields.Char(string="Type")
    brand = fields.Char(string="Brand")
    model_name = fields.Char(string="Model")
    serial_number = fields.Char(string="Serial No.")
    status = fields.Selection(
        [
            ("in_use", "In Use"),
            ("standby", "Standby"),
            ("out_of_order", "Out of Order"),
            ("scrapped", "Scrapped"),
        ],
        string="Status",
        default="in_use",
    )

    consumable_line_ids = fields.One2many(
        "equipment.consumable.line", "equipment_id", string="Consumables"
    )
    parent_id = fields.Many2one("maintenance.equipment", string="Parent Equipment")
    child_ids = fields.One2many(
        "maintenance.equipment", "parent_id", string="Sub-components"
    )
    bt_ids = fields.One2many("gmao.bt", "equipment_id", string="Historique des BT")
    technician_user_id = fields.Many2one(
        "res.users",
        string="Responsible",
        required=True,
        tracking=True,
        default=lambda self: self.env.uid,
    )

    installation_date = fields.Date(string="Installation Date")
    scrap_date = fields.Date(string="Scrap Date")
    maintenance_cycle = fields.Text(string="Maintenance Cycle Notes")

    document_ids = fields.Many2many("ir.attachment", string="Documents")
    estimated_next_failure = fields.Date(
        string="Estimated Next Failure", compute="_compute_next_failure", store=True
    )
    expected_mtbf = fields.Integer(
        string="Expected MTBF (Days)", help="Average days between failures"
    )
    latest_failure_date = fields.Date(string="Last Failure Date")

    @api.depends("latest_failure_date", "effective_date", "expected_mtbf")
    def _compute_next_failure(self):
        for eq in self:
            if eq.latest_failure_date and eq.expected_mtbf:
                eq.estimated_next_failure = eq.latest_failure_date + timedelta(
                    days=eq.expected_mtbf
                )
            elif eq.effective_date and eq.expected_mtbf:
                eq.estimated_next_failure = eq.effective_date + timedelta(
                    days=eq.expected_mtbf
                )
            else:
                eq.estimated_next_failure = False

    def compute_mtbf_from_failures(self):
        Maintenance = self.env["maintenance.request"]
        for eq in self:
            failures = Maintenance.search(
                [
                    ("equipment_id", "=", eq.id),
                    (
                        "maintenance_type",
                        "in",
                        ["corrective", "curative", "predictive"],
                    ),
                    ("request_date", "!=", False),
                ],
                order="request_date asc",
            )

            if len(failures) >= 2:
                intervals = [
                    (failures[i].request_date - failures[i - 1].request_date).days
                    for i in range(1, len(failures))
                ]
                eq.expected_mtbf = sum(intervals) // len(intervals)
                eq.latest_failure_date = failures[-1].request_date

    def create_or_update_predictive_plan(self):
        MaintenancePlan = self.env["maintenance.plan"]
        for eq in self:
            if not eq.expected_mtbf or not eq.latest_failure_date:
                continue

            plan = MaintenancePlan.search(
                [("equipment_id", "=", eq.id), ("maintenance_type", "=", "predictive")],
                limit=1,
            )

            values = {
                "name": f"Predictive Plan for {eq.name}",
                "equipment_id": eq.id,
                "maintenance_type": "predictive",
                "interval_number": eq.expected_mtbf,
                "interval_type": "days",
                "next_date": eq.latest_failure_date + timedelta(days=eq.expected_mtbf),
                "active": True,
            }

            if plan:
                plan.write(values)
            else:
                MaintenancePlan.create(values)

    def action_open_bt_history(self):
        self.ensure_one()
        return {
            "name": f"Historique des BT - {self.name}",
            "type": "ir.actions.act_window",
            "res_model": "gmao.bt",
            "view_mode": "tree,form",
            "domain": [("equipment_id", "=", self.id)],
            "context": {"default_equipment_id": self.id},
            "target": "current",
        }
