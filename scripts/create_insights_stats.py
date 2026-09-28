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
    created = {"source": source, "workbooks": {}}

    user_wb = _workbook("User stats")
    queries = []
    queries.append(
        _native_query(
            user_wb,
            "Users by type",
            source,
            """
            SELECT user_type, IF(enabled = 1, 'Enabled', 'Disabled') AS status, COUNT(*) AS users
            FROM tabUser
            WHERE name NOT IN ('Guest', 'Administrator')
            GROUP BY user_type, enabled
            ORDER BY users DESC
            """,
            0,
        )
    )
    queries.append(
        _native_query(
            user_wb,
            "New users by day",
            source,
            """
            SELECT DATE(creation) AS day, COUNT(*) AS new_users
            FROM tabUser
            WHERE name NOT IN ('Guest', 'Administrator')
              AND creation >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            GROUP BY DATE(creation)
            ORDER BY day
            """,
            1,
        )
    )
    if _table_exists("tabActivity Log"):
        queries.append(
            _native_query(
                user_wb,
                "Logins by day",
                source,
                """
                SELECT DATE(creation) AS day, COUNT(*) AS logins
                FROM `tabActivity Log`
                WHERE operation = 'Login'
                  AND creation >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
                GROUP BY DATE(creation)
                ORDER BY day
                """,
                2,
            )
        )
    created["workbooks"]["User stats"] = queries

    web_wb = _workbook("Website stats")
    web_queries = []
    if _table_exists("tabWeb Page View"):
        web_queries.append(
            _native_query(
                web_wb,
                "Page views by path",
                source,
                """
                SELECT path, COUNT(*) AS views
                FROM `tabWeb Page View`
                WHERE creation >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
                GROUP BY path
                ORDER BY views DESC
                LIMIT 50
                """,
                0,
            )
        )
        web_queries.append(
            _native_query(
                web_wb,
                "Page views by day",
                source,
                """
                SELECT DATE(creation) AS day, COUNT(*) AS views
                FROM `tabWeb Page View`
                WHERE creation >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
                GROUP BY DATE(creation)
                ORDER BY day
                """,
                1,
            )
        )
    elif _table_exists("tabView Log"):
        web_queries.append(
            _native_query(
                web_wb,
                "Document views by type",
                source,
                """
                SELECT reference_doctype, COUNT(*) AS views
                FROM `tabView Log`
                WHERE creation >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
                GROUP BY reference_doctype
                ORDER BY views DESC
                """,
                0,
            )
        )
    if _table_exists("tabBlog Post"):
        web_queries.append(
            _native_query(
                web_wb,
                "Published blog posts",
                source,
                """
                SELECT DATE(published_on) AS day, COUNT(*) AS posts
                FROM `tabBlog Post`
                WHERE published = 1
                GROUP BY DATE(published_on)
                ORDER BY day DESC
                LIMIT 30
                """,
                2,
            )
        )
    if _table_exists("tabWeb Page"):
        web_queries.append(
            _native_query(
                web_wb,
                "Web pages",
                source,
                """
                SELECT published, COUNT(*) AS pages
                FROM `tabWeb Page`
                GROUP BY published
                """,
                3,
            )
        )
    if not web_queries:
        frappe.throw("No website tables found for Insights")
    created["workbooks"]["Website stats"] = web_queries
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
