import frappe
from frappe.utils import now_datetime, get_datetime, time_diff_in_seconds

ESCALATION_EMAILS = [
    "ganesh.shinde@mailit.co.in",
    "amey.shirodkar@mailit.co.in",
    "mahesh.shirodkar@mailit.co.in",
]

ESCALATION_MINUTES = 30

PENDING_STATES_MAP = {
    "Purchase Order": ["Send for Manager Approval", "Send for Final Approval"],
    "Purchase Invoice": ["Send for Manager Approval", "Send for Final Approval"],
    "Purchase Receipt": ["Send for Manager Approval", "Send for Final Approval"],  
    "Sales Order": ["Send for Manager Approval", "Send for Final Approval"],
    "Sales Invoice": ["Send for Manager Approval", "Send for Final Approval"],
    "Delivery Note": ["Send for Manager Approval", "Send for Final Approval"],
    "Stock Entry": ["Send for Manager Approval", "Send for Final Approval"],
}


def on_workflow_state_change(doc, method=None):
    pending_states = PENDING_STATES_MAP.get(doc.doctype, [])

    if doc.workflow_state in pending_states:
        old_doc = doc.get_doc_before_save()
        old_state = old_doc.workflow_state if old_doc else None

        if old_state != doc.workflow_state:
            frappe.db.set_value(
                doc.doctype,
                doc.name,
                {
                    "custom_approval_pending_since": now_datetime(),
                    "custom_escalation_sent": 0,
                },
                update_modified=False,
            )
    else:
        frappe.db.set_value(
            doc.doctype,
            doc.name,
            {
                "custom_approval_pending_since": None,
                "custom_escalation_sent": 0,
            },
            update_modified=False,
        )


def send_approval_escalations():
    for doctype, pending_states in PENDING_STATES_MAP.items():
        pending_entries = frappe.get_all(
            doctype,
            filters={
                "workflow_state": ["in", pending_states],
                "custom_approval_pending_since": ["is", "set"],
                "custom_escalation_sent": 0,
            },
            fields=["name", "workflow_state", "custom_approval_pending_since"],
        )

        for entry in pending_entries:
            pending_since = get_datetime(entry.custom_approval_pending_since)
            elapsed_minutes = time_diff_in_seconds(now_datetime(), pending_since) / 60

            if elapsed_minutes >= ESCALATION_MINUTES:
                frappe.sendmail(
                    recipients=ESCALATION_EMAILS,
                    subject=f"Escalation: {doctype} {entry.name} pending approval",
                    message=f"""
                        {doctype} <b>{entry.name}</b> has been pending in
                        <b>{entry.workflow_state}</b> for more than {ESCALATION_MINUTES} minutes
                        without action.<br><br>
                        Please review and approve/reject it at the earliest.<br><br>
                        <a href="{frappe.utils.get_url()}/app/{frappe.scrub(doctype).replace('_', '-')}/{entry.name}">Open {doctype}</a>
                    """,
                )
                frappe.db.set_value(doctype, entry.name, "custom_escalation_sent", 1)

    frappe.db.commit()