import frappe
from frappe import _
from frappe.utils import flt
from frappe.model.naming import make_autoname



@frappe.whitelist()
def get_available_barcodes(store, location, item_code):

    receipts = frappe.db.sql("""
        SELECT
            custom_batch_barcode,
            SUM(qty) as received_qty
        FROM `tabStock Entry Detail` sed
        INNER JOIN `tabStock Entry` se
            ON se.name = sed.parent
        WHERE se.stock_entry_type = 'Material Receipt'
          AND se.docstatus = 1
          AND sed.custom_store = %(store)s
          AND sed.custom_location = %(location)s
          AND sed.item_code = %(item_code)s
          AND sed.custom_batch_barcode IS NOT NULL
        GROUP BY sed.custom_batch_barcode
    """, {
        "store": store,
        "location": location,
        "item_code": item_code
    }, as_dict=True)

    available = []

    for r in receipts:

        issued = frappe.db.sql("""
            SELECT COALESCE(SUM(sed.qty),0)
            FROM `tabStock Entry Detail` sed
            INNER JOIN `tabStock Entry` se
                ON se.name = sed.parent
            WHERE se.stock_entry_type = 'Material Issue'
              AND se.docstatus = 1
              AND sed.custom_select_batch_barcode_ = %(barcode)s
        """, {
            "barcode": r.custom_batch_barcode
        })[0][0]

        balance = r.received_qty - issued

        if balance > 0:
            available.append({
                "barcode": r.custom_batch_barcode,
                "balance": balance
            })

    return available

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_store_addresses(doctype, txt, searchfield, start, page_len, filters):

    if not filters.get("store"):
        return []

    store = frappe.get_doc("Store", filters.get("store"))

    addresses = [d.address for d in store.location if d.address]

    if not addresses:
        return []

    return frappe.db.sql("""
        SELECT name
        FROM `tabAddress`
        WHERE name IN %(addresses)s
          AND name LIKE %(txt)s
        ORDER BY name
        LIMIT %(start)s, %(page_len)s
    """, {
        "addresses": tuple(addresses),
        "txt": f"%{txt}%",
        "start": start,
        "page_len": page_len
    })


def stock_entry_validate(doc, method):
    if doc.stock_entry_type != "Material Receipt":
        return

    for item in doc.items:
        if not item.custom_batch_barcode:
            item.custom_batch_barcode = make_autoname("TIN.#####")


def validate_material_issue(doc, method):

    if doc.stock_entry_type == "Material Issue":

        for row in doc.items:

            if not row.custom_select_batch_barcode_:
                continue

            receipt_qty = frappe.db.sql("""
                SELECT COALESCE(SUM(sed.qty),0)
                FROM `tabStock Entry Detail` sed
                INNER JOIN `tabStock Entry` se
                    ON se.name = sed.parent
                WHERE se.docstatus = 1
                AND se.stock_entry_type = 'Material Receipt'
                AND sed.custom_batch_barcode = %s
                AND sed.item_code = %s
                AND sed.custom_store = %s
                AND sed.custom_location = %s
            """, (
                row.custom_select_batch_barcode_,
                row.item_code,
                row.custom_store,
                row.custom_location
            ))[0][0]

            issued_qty = frappe.db.sql("""
                SELECT COALESCE(SUM(sed.qty),0)
                FROM `tabStock Entry Detail` sed
                INNER JOIN `tabStock Entry` se
                    ON se.name = sed.parent
                WHERE se.docstatus = 1
                AND se.stock_entry_type = 'Material Issue'
                AND sed.custom_select_batch_barcode_ = %s
                AND sed.item_code = %s
                AND sed.custom_store = %s
                AND sed.custom_location = %s
            """, (
                row.custom_select_batch_barcode_,
                row.item_code,
                row.custom_store,
                row.custom_location
            ))[0][0]

            balance = receipt_qty - issued_qty

            if row.qty > balance:
                frappe.throw(
                    f"Barcode {row.custom_select_batch_barcode_} has only {balance} qty available. "
                    f"You are trying to issue {row.qty}."
                )

def get_remaining_po_items(po):
    po_refs = [po.name]
    if po.get("order_confirmation_no"):
        po_refs.append(po.order_confirmation_no)

    # custom_po_no lives on the Stock Entry (PARENT) doctype, not on Stock Entry Detail
    issued_entries = frappe.get_all(
        "Stock Entry",
        filters={
            "purpose": "Material Issue",
            "docstatus": 1,
            "custom_po_no": ["in", po_refs],   # <-- parent-level field
        },
        pluck="name",
    )

    issued_qty_map = {}
    if issued_entries:
        issued_items = frappe.get_all(
            "Stock Entry Detail",
            filters={"parent": ["in", issued_entries]},
            fields=["item_code", "qty"],
        )
        for row in issued_items:
            issued_qty_map[row.item_code] = issued_qty_map.get(row.item_code, 0) + flt(row.qty)

    remaining = []
    for item in po.items:
        item_code = item.item_code
        balance_to_consume = flt(issued_qty_map.get(item_code, 0))

        if balance_to_consume >= flt(item.qty):
            # this row fully consumed by issued qty; deduct and skip
            issued_qty_map[item_code] = balance_to_consume - flt(item.qty)
            continue

        # partially or not consumed
        remaining_qty = flt(item.qty) - balance_to_consume
        issued_qty_map[item_code] = 0

        if remaining_qty > 0:
            remaining.append((item, remaining_qty))

    return remaining

@frappe.whitelist()
def get_remaining_po_items_summary(po_name):
    po = frappe.get_doc("Purchase Order", po_name)
    remaining = get_remaining_po_items(po)
    return [
        {
            "item_code": item.item_code,
            "item_name": item.item_name,
            "po_qty": item.qty,
            "remaining_qty": remaining_qty,
        }
        for item, remaining_qty in remaining
    ]

@frappe.whitelist()
def create_sales_order_from_po(po_name, customer, delivery_date=None):
    po = frappe.get_doc("Purchase Order", po_name)

    if po.docstatus != 1:
        frappe.throw(_("Purchase Order must be submitted"))

    remaining_rows = get_remaining_po_items(po)

    if not remaining_rows:
        frappe.throw(_("All items against this Purchase Order have already been issued. Nothing remaining to sell."))

    so = frappe.new_doc("Sales Order")
    so.customer = customer
    so.company = po.company
    so.transaction_date = po.transaction_date

    # Header delivery_date: earliest schedule_date among the remaining rows
    # (falls back to the passed-in value, then today+7, if none found)
    earliest_schedule_date = min(
        (item.schedule_date for item, _qty in remaining_rows if item.schedule_date),
        default=None,
    )
    so.delivery_date = (
        earliest_schedule_date
        or delivery_date
        or frappe.utils.add_days(frappe.utils.nowdate(), 7)
    )

    for item, remaining_qty in remaining_rows:
        item_delivery_date = item.schedule_date or delivery_date or so.delivery_date

        so.append("items", {
            "item_code": item.item_code,
            "item_name": item.item_name,
            "description": item.description,
            "qty": remaining_qty,
            "uom": item.uom,
            "stock_uom": item.stock_uom,
            "conversion_factor": item.conversion_factor,
            "warehouse": item.warehouse,
            "purchase_order": po.name,
            "purchase_order_item": item.name,
            "delivery_date": item_delivery_date,
        })

    so.insert()
    return so.name