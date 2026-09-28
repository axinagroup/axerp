"""Create Insights workbooks for website stats and user stats.

Runs inside the bench: bench --site erp.tspgusa.com execute scripts.create_insights_stats.run
or via frappe.init from the container. The function is self-contained so it can
also be loaded with runpy.
"""

import json

import frappe


def _site_source():
    name = frappe.db.get_value("Insights Data Source v3", {"is_site_db": 1}, "name")
    if not name:
        name = frappe.db.get_value("Insights Data Source v3", {"title": ["like", "%site%"]}, "name")
    if not name:
        frappe.throw("No Insights site data source found")
    return name


def _table_exists(table):
    return bool(frappe.db.sql("SHOW TABLES LIKE %s", table))


def _share_workbook(name):
    exists = frappe.db.exists(
        "DocShare",
        {"share_doctype": "Insights Workbook", "share_name": name, "everyone": 1},
    )
    if exists:
        return
    frappe.share.add(
        "Insights Workbook",
        name,
        read=1,
        write=0,
        share=0,
        everyone=1,
        notify=0,
    )


def _dimension(column_name):
    return {"column_name": column_name, "dimension_name": column_name, "data_type": "String"}


def _measure(column_name):
    return {
        "column_name": column_name,
        "measure_name": column_name,
        "data_type": "Integer",
        "aggregation": "sum",
    }


def _chart(workbook, title, query, rows, value, sort_order):
    existing = frappe.db.get_value(
        "Insights Chart v3", {"workbook": workbook, "title": title}, "name"
    )
    doc = frappe.get_doc("Insights Chart v3", existing) if existing else frappe.new_doc("Insights Chart v3")
    doc.title = title
    doc.workbook = workbook
    doc.query = query
    doc.chart_type = "Table"
    doc.is_standard = 0
    doc.visibility = "Everyone"
    doc.sort_order = sort_order
    doc.config = json.dumps(
        {
            "rows": [_dimension(column) for column in rows],
            "columns": [],
            "values": [_measure(value)],
        }
    )
    doc.save(ignore_permissions=True)
    return doc.name


def _dashboard(workbook, title, charts):
    existing = frappe.db.get_value(
        "Insights Dashboard v3", {"workbook": workbook, "title": title}, "name"
    )
    doc = (
        frappe.get_doc("Insights Dashboard v3", existing)
        if existing
        else frappe.new_doc("Insights Dashboard v3")
    )
    doc.title = title
    doc.workbook = workbook
    doc.is_standard = 0
    doc.visibility = "Everyone"
    doc.items = [
        {
            "type": "chart",
            "chart": chart,
            "layout": {"i": frappe.generate_hash(length=8), "x": 0, "y": index * 14, "w": 20, "h": 12},
        }
        for index, chart in enumerate(charts)
    ]
    doc.save(ignore_permissions=True)
    return doc.name


def _native_query(workbook, title, source, sql, sort_order):
    existing = frappe.db.get_value(
        "Insights Query v3", {"workbook": workbook, "title": title}, "name"
    )
    doc = frappe.get_doc("Insights Query v3", existing) if existing else frappe.new_doc("Insights Query v3")
    doc.title = title
    doc.workbook = workbook
    doc.is_native_query = 1
    doc.is_builder_query = 0
    doc.is_script_query = 0
    doc.use_live_connection = 1
    doc.sort_order = sort_order
    doc.operations = json.dumps(
        [{"type": "sql", "data_source": source, "raw_sql": sql.strip()}]
    )
    doc.save(ignore_permissions=True)
    return doc.name


def _workbook(title):
    name = frappe.db.get_value("Insights Workbook", {"title": title}, "name")
    if name:
        return name
    doc = frappe.get_doc({"doctype": "Insights Workbook", "title": title})
    doc.is_standard = 0
    doc.insert(ignore_permissions=True)
    return doc.name


def run():
    frappe.set_user("Administrator")
    for dt in (
        "insights_workbook",
        "insights_query_v3",
        "insights_chart_v3",
        "insights_dashboard_v3",
        "insights_data_source_v3",
    ):
        frappe.reload_doc("insights", "doctype", dt, force=True)
    frappe.db.commit()
    source = _site_source()
    created = {"source": source, "workbooks": {}, "dashboards": {}}

    specs = {
        "User stats": [
            (
                "Users by type",
                ["user_type", "status"],
                "users",
                """
                SELECT user_type, IF(enabled = 1, 'Enabled', 'Disabled') AS status, COUNT(*) AS users
                FROM tabUser
                WHERE name NOT IN ('Guest', 'Administrator')
                GROUP BY user_type, enabled
                ORDER BY users DESC
                """,
            ),
            (
                "New users by day",
                ["day"],
                "new_users",
                """
                SELECT DATE(creation) AS day, COUNT(*) AS new_users
                FROM tabUser
                WHERE name NOT IN ('Guest', 'Administrator')
                  AND creation >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
                GROUP BY DATE(creation)
                ORDER BY day
                """,
            ),
        ],
        "Website stats": [],
    }
    if _table_exists("tabActivity Log"):
        specs["User stats"].append(
            (
                "Logins by day",
                ["day"],
                "logins",
                """
                SELECT DATE(creation) AS day, COUNT(*) AS logins
                FROM `tabActivity Log`
                WHERE operation = 'Login'
                  AND creation >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
                GROUP BY DATE(creation)
                ORDER BY day
                """,
            )
        )
    if _table_exists("tabWeb Page View"):
        specs["Website stats"].extend(
            [
                (
                    "Page views by path",
                    ["path"],
                    "views",
                    """
                    SELECT path, COUNT(*) AS views
                    FROM `tabWeb Page View`
                    WHERE creation >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
                    GROUP BY path
                    ORDER BY views DESC
                    LIMIT 50
                    """,
                ),
                (
                    "Page views by day",
                    ["day"],
                    "views",
                    """
                    SELECT DATE(creation) AS day, COUNT(*) AS views
                    FROM `tabWeb Page View`
                    WHERE creation >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
                    GROUP BY DATE(creation)
                    ORDER BY day
                    """,
                ),
            ]
        )
    elif _table_exists("tabView Log"):
        specs["Website stats"].append(
            (
                "Document views by type",
                ["reference_doctype"],
                "views",
                """
                SELECT reference_doctype, COUNT(*) AS views
                FROM `tabView Log`
                WHERE creation >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
                GROUP BY reference_doctype
                ORDER BY views DESC
                """,
            )
        )
    if _table_exists("tabBlog Post"):
        specs["Website stats"].append(
            (
                "Published blog posts",
                ["day"],
                "posts",
                """
                SELECT DATE(published_on) AS day, COUNT(*) AS posts
                FROM `tabBlog Post`
                WHERE published = 1
                GROUP BY DATE(published_on)
                ORDER BY day DESC
                LIMIT 30
                """,
            )
        )
    if _table_exists("tabWeb Page"):
        specs["Website stats"].append(
            (
                "Web pages",
                ["published"],
                "pages",
                """
                SELECT published, COUNT(*) AS pages
                FROM `tabWeb Page`
                GROUP BY published
                """,
            )
        )
    if not specs["Website stats"]:
        frappe.throw("No website tables found for Insights")

    for title, items in specs.items():
        workbook = _workbook(title)
        _share_workbook(workbook)
        charts = []
        queries = []
        for index, (query_title, rows, value, sql) in enumerate(items):
            query = _native_query(workbook, query_title, source, sql, index)
            queries.append(query)
            charts.append(_chart(workbook, query_title, query, rows, value, index))
        dashboard = _dashboard(workbook, title, charts)
        created["workbooks"][title] = queries
        created["dashboards"][title] = dashboard
    frappe.db.commit()
    print(json.dumps(created))
    return created


if __name__ == "__main__":
    frappe.init(site="erp.tspgusa.com", sites_path="/home/frappe/frappe-bench/sites")
    frappe.connect()
    try:
        run()
    finally:
        frappe.destroy()
