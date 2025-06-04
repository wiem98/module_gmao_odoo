from odoo import models, fields, api, _
from datetime import datetime, timedelta
from odoo.exceptions import UserError



class SaleOrder(models.Model):
    _inherit = 'sale.order'

    project_id = fields.Many2one('project.project', string='Linked Project', readonly=True)

    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            # Build the project name from customer
            project_name = f"{order.name} - {order.partner_id.name}"

            # Create the linked project
            project = self.env['project.project'].create({
                'name': project_name,
                'partner_id': order.partner_id.id,
            })
            order.project_id = project.id

            # Log the project creation in the chatter (rendered as plain text now to avoid <b> issues)
            order.message_post(
                body=f"📁 Project {project.name} created and linked to this Sales Order.",
                subtype_id=self.env.ref("mail.mt_note").id
            )

            # Retrieve existing stages (must be already configured manually)
            stage_mapping = {
                'Waiting to Purchase': self.env['project.task.type'].search([('name', '=', 'Waiting to Purchase')], limit=1),
                'Realisation': self.env['project.task.type'].search([('name', '=', 'Realisation')], limit=1),
                'Done': self.env['project.task.type'].search([('name', '=', 'Done')], limit=1),
                'Intervention': self.env['project.task.type'].search([('name', '=', 'Intervention')], limit=1),
            }

            # Assign stages to project in correct order
            project.type_ids = [(6, 0, [stage_mapping[name].id for name in ['Waiting to Purchase', 'Realisation', 'Done', 'Intervention'] if stage_mapping[name]])]

            # Prepare and create tasks based on sale order lines
            task_values = []
            for line in order.order_line:
                product = line.product_id
                task_stage = False

                if hasattr(product, 'product_category_type'):
                    if product.product_category_type == 'goods':
                        task_stage = stage_mapping['Waiting to Purchase'].id if stage_mapping['Waiting to Purchase'] else False
                    elif product.product_category_type in ('service', 'combo'):
                        task_stage = stage_mapping['Realisation'].id if stage_mapping['Realisation'] else False
                else:
                    if product.type in ['product', 'consu']:
                        task_stage = stage_mapping['Waiting to Purchase'].id if stage_mapping['Waiting to Purchase'] else False
                    elif product.type == 'service':
                        task_stage = stage_mapping['Realisation'].id if stage_mapping['Realisation'] else False

                task = {
                    'name': line.name or product.name,
                    'project_id': project.id,
                }
                if task_stage:
                    task['stage_id'] = task_stage

                task_values.append(task)

            if task_values:
                self.env['project.task'].create(task_values)

        return res

class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_add_main_doeuvre(self):
        self.ensure_one()

        # Try to get linked sale order via invoice origin
        sale_order = self.env['sale.order'].search([('name', '=', self.invoice_origin)], limit=1)
        if not sale_order:
            raise UserError(_("No linked Sale Order found via 'invoice_origin'."))

        # Get the linked project
        project = sale_order.project_id
        if not project:
            raise UserError(_("The linked Sale Order has no associated project."))

        # Force recompute to ensure hours are up to date
        project = self.env['project.project'].browse(project.id)  # refetch with updated data
        project.total_time_spent = sum(project.task_ids.mapped('total_hours_spent'))  # manual recompute

        if float(project.total_time_spent) < 0.01:
          raise UserError(_("No significant time has been recorded on the linked project."))

        # Get or create "Main-dœuvre" product
        product = self.env['product.product'].search([('name', '=', 'Main-dœuvre')], limit=1)
        if not product:
            product = self.env['product.product'].create({
                'name': 'Main-dœuvre',
                'type': 'service',
                'uom_id': self.env.ref('uom.product_uom_hour').id,
            })

        # Prevent duplicate addition
        if self.invoice_line_ids.filtered(lambda line: line.product_id == product):
            raise UserError(_("A 'Main-dœuvre' line already exists in this invoice."))

        # Determine account
        account = product.property_account_income_id or product.categ_id.property_account_income_categ_id
        if not account:
            raise UserError(_("No income account is set on the product or its category."))

        # Create the invoice line
        self.env['account.move.line'].create({
            'move_id': self.id,
            'product_id': product.id,
            'quantity': project.total_time_spent,
            'price_unit': 0.0,  # User can update manually
            'name': f'Main-dœuvre for project {project.name}',
            'account_id': account.id,
        })

        return True
    
class Project(models.Model):
    _inherit = 'project.project'

    total_time_spent = fields.Float(string="Total Time Spent (hrs)", compute="_compute_total_time_spent", store=True)
    opened_user_ids = fields.Many2many('res.users', string="Users Who Opened")
    is_new_project = fields.Boolean(string="Is New Project", compute="_compute_is_new_project", store=False)
    current_user_id = fields.Integer(string="Current User ID", compute="_compute_current_user_id")
    stage_id = fields.Many2one('project.project.stage', string='Stage')
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
        domain=[('customer_rank', '>', 0)]
    )


    @api.model
    def _update_project_stage_based_on_tasks(self):
        stage_done = self.env['project.task.type'].search([('name', '=', 'Done')], limit=1)
        stage_project_done = self.env['project.project.stage'].search([('name', '=', 'Completed')], limit=1)
        for project in self:
            if all(task.stage_id == stage_done for task in project.task_ids):
                project.stage_id = stage_project_done.id

    def check_and_notify_ready_for_invoice(self):
        done_stage = self.env['project.task.type'].search([('name', '=', 'Done')], limit=1)
        if not done_stage:
            return

        for project in self:
            all_done = all(task.stage_id == done_stage for task in project.task_ids)
            if all_done and not project.message_main_attachment_id:  # Avoid spamming
                # Send notification
                template = self.env.ref('sale_project_auto.email_template_project_ready_invoice', raise_if_not_found=False)
                if template:
                    template.send_mail(project.id, force_send=True)
                else:
                    project.message_post(body=_("🧾 All tasks are marked Done. Project is ready to be invoiced."))

    def _compute_current_user_id(self):
        uid = self.env.user.id
        for record in self:
            record.current_user_id = uid

    @api.depends('create_date')
    def _compute_is_new_project(self):
        today = fields.Date.context_today(self)
        for project in self:
            if project.create_date:
                delta = today - project.create_date.date()
                project.is_new_project = delta.days <= 7
            else:
                project.is_new_project = False

    @api.depends('task_ids.total_hours_spent')
    def _compute_total_time_spent(self):
        for project in self:
            project.total_time_spent = sum(project.task_ids.mapped('total_hours_spent'))

    def mark_as_opened(self):
        for project in self:
            if self.env.user not in project.opened_user_ids:
                project.opened_user_ids = [(4, self.env.user.id)]

    def read(self, fields=None, load='_classic_read'):
        projects = super().read(fields=fields, load=load)
        self.mark_as_opened()
        return projects

class ProjectTaskType(models.Model):
    _inherit = 'project.task.type'

    company_id = fields.Many2one('res.company', string="Company", default=lambda self: self.env.company)

class ProjectStage(models.Model):
    _inherit = 'project.project.stage'
    _order = 'sequence'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=1)
    company_id = fields.Many2one('res.company', string="Company", default=lambda self: self.env.company)


class ProjectTask(models.Model):
    _inherit = 'project.task'

    checkin_state = fields.Selection([
        ('out', 'Checked Out'),
        ('in', 'Checked In'),
    ], default='out')
    checkin_time = fields.Datetime(string="Check-In Time")
    total_hours_spent = fields.Float(string="Total Hours Spent")
    maintenance_request_id = fields.Many2one('maintenance.request', string="Maintenance Request")
    
    def write(self, vals):
        # Automatically check out if moving to "done" stage
        if 'state' in vals and vals['state'] == '1_done':
            for task in self:
                if task.checkin_state == 'in':
                    if task.checkin_time:
                        delta = fields.Datetime.now() - task.checkin_time
                        task.total_hours_spent += delta.total_seconds() / 3600
                    task.checkin_state = 'out'
                    task.checkin_time = False

                # 1. Auto-close linked maintenance request
                if task.maintenance_request_id:

                    # Search for a stage named "Done"
                    done_stage = self.env['maintenance.stage'].search([('name', 'ilike', 'done')], limit=1)
                    if task.maintenance_request_id.stage_id != done_stage:
                        task.maintenance_request_id.write({'stage_id': done_stage.id})
                        #print(task.maintenance_request_id.stage_id)

                # 2. Mark related activities as done
                activities = self.env['mail.activity'].search([
                    ('res_model', '=', 'project.task'),
                    ('res_id', '=', task.id),
                    ('activity_type_id', '!=', False),  # Only real activities
                    ('date_deadline', '!=', False),     # Optional filter
                ])
                for activity in activities:
                    activity.action_feedback(feedback="Marked as done with task.")

        # If stage_id is changed, check if project is ready for invoice
        if 'stage_id' in vals:
            projects = self.mapped('project_id')
            projects.check_and_notify_ready_for_invoice()
        return super().write(vals)


    def action_toggle_checkin(self):
        for task in self:
            if task.checkin_state == 'out':
                # Do Check-In
                task.checkin_state = 'in'
                task.checkin_time = fields.Datetime.now()
                
                if not task.state == '03_approved':
                    task.state = '03_approved'
            elif task.checkin_state == 'in':
                # Do Check-Out
                if task.checkin_time:
                    delta = fields.Datetime.now() - task.checkin_time
                    task.total_hours_spent += delta.total_seconds() / 3600
                task.checkin_state = 'out'
                task.checkin_time = False