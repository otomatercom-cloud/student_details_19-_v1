/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

export class StudentSaasDashboard extends Component {
    static template = "student_details_19.StudentSaasDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            error: "",
            data: null,
        });
        onWillStart(() => this.loadData());
    }

    async loadData() {
        this.state.loading = true;
        this.state.error = "";
        try {
            this.state.data = await this.orm.call(
                "student.batch", "get_saas_dashboard", []
            );
        } catch (e) {
            console.error("SaaS dashboard load failed", e);
            this.state.error = "Failed to load the dashboard. Please refresh.";
        } finally {
            this.state.loading = false;
        }
    }

    get d() {
        return this.state.data || {};
    }

    fmt(n) {
        return (n || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    openBatch(batch) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: batch.batch_name,
            res_model: "student.details",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [["batch_id", "=", batch.batch_id]],
            target: "current",
        });
    }

    openFullyPaid() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Fully Paid",
            res_model: "student.enrollment",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [["payment_status", "=", "paid"]],
            target: "current",
        });
    }

    openPending() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Pending Payment",
            res_model: "student.enrollment",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [["payment_status", "in", ["unpaid", "partial"]]],
            target: "current",
        });
    }

    openDropped() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Dropped",
            res_model: "student.enrollment",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [["status", "=", "dropped"]],
            target: "current",
        });
    }
}

registry.category("actions").add("student_details_19.saas_dashboard", StudentSaasDashboard);
