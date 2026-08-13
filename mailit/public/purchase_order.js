frappe.ui.form.on('Purchase Order', {
    refresh: function (frm) {
        if (frm.doc.docstatus === 1 && !["Closed", "Cancelled"].includes(frm.doc.status)) {
            frm.add_custom_button(__('Sales Order'), function () {
                frappe.call({
                    method: "mailit.config.api.get_remaining_po_items_summary",
                    args: { po_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __("Checking remaining quantities..."),
                    callback: function (r) {
                        if (!r.message || !r.message.length) {
                            frappe.msgprint(__("All items against this Purchase Order have already been issued."));
                            return;
                        }

                        let items_html = r.message.map(row =>
                            `<tr>
                                <td>${row.item_code}</td>
                                <td>${row.po_qty}</td>
                                <td><b>${row.remaining_qty}</b></td>
                            </tr>`
                        ).join("");

                        let d = new frappe.ui.Dialog({
                            title: __('Create Sales Order for Remaining Qty'),
                            fields: [
                                {
                                    fieldtype: 'HTML',
                                    fieldname: 'preview',
                                    options: `
                                        <table class="table table-bordered">
                                            <thead>
                                                <tr><th>Item</th><th>PO Qty</th><th>Remaining Qty</th></tr>
                                            </thead>
                                            <tbody>${items_html}</tbody>
                                        </table>`
                                },
                                {
                                    fieldtype: 'Link',
                                    fieldname: 'customer',
                                    label: __('Customer'),
                                    options: 'Customer',
                                    reqd: 1,
                                },
                                {
                                    fieldtype: 'Date',
                                    fieldname: 'delivery_date',
                                    label: __('Delivery Date'),
                                },
                            ],
                            primary_action_label: __('Create Sales Order'),
                            primary_action: function (values) {
                                frappe.call({
                                    method: "mailit.config.api.create_sales_order_from_po",
                                    args: {
                                        po_name: frm.doc.name,
                                        customer: values.customer,
                                        delivery_date: values.delivery_date,
                                    },
                                    freeze: true,
                                    freeze_message: __("Creating Sales Order..."),
                                    callback: function (res) {
                                        if (res.message) {
                                            d.hide();
                                            frappe.set_route("Form", "Sales Order", res.message);
                                        }
                                    },
                                });
                            },
                        });

                        d.show();
                    },
                });
            }, __('Create'));
        }
    },
});