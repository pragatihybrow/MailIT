import frappe
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