frappe.ui.form.on("Stock Entry", {
    refresh(frm) {
        frm.fields_dict.items.grid.get_field("custom_location").get_query =
            function(doc, cdt, cdn) {

                let row = locals[cdt][cdn];

                return {
                    query: "mailit.config.api.get_store_addresses",
                    filters: {
                        store: row.custom_store || ""
                    }
                };
            };
    }
});
frappe.ui.form.on("Stock Entry Detail", {
    item_code: load_barcodes,
    custom_store: load_barcodes,
    custom_location: load_barcodes
});

function load_barcodes(frm, cdt, cdn) {

    if (frm.doc.stock_entry_type !== "Material Issue") {
        return;
    }

    let row = locals[cdt][cdn];

    if (!row.item_code || !row.custom_store || !row.custom_location) {
        return;
    }

    frappe.call({
        method: "mailit.config.api.get_available_barcodes",
        args: {
            store: row.custom_store,
            location: row.custom_location,
            item_code: row.item_code
        },
        callback(r) {

            if (!r.message || !r.message.length) {
                return;
            }

            frappe.prompt(
                [{
                    fieldname: "barcode",
                    label: "Barcode",
                    fieldtype: "Select",
                    options: r.message.map(d =>
                        `${d.barcode} (Bal: ${d.balance})`
                    ).join("\n")
                }],
                (values) => {
                    frappe.model.set_value(
                        cdt,
                        cdn,
                        "custom_select_batch_barcode_",
                        values.barcode.split(" ")[0]
                    );
                }
            );
        }
    });
}