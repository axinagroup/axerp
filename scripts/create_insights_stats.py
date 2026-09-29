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


def _dimension(column_name, data_type="String"):
    return {"column_name": column_name, "dimension_name": column_name, "data_type": data_type}


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


def _set_chart(workbook, title, query, chart_type, config, sort_order):
    existing = frappe.db.get_value(
        "Insights Chart v3", {"workbook": workbook, "title": title}, "name"
    )
    doc = frappe.get_doc("Insights Chart v3", existing) if existing else frappe.new_doc("Insights Chart v3")
    doc.title = title
    doc.workbook = workbook
    doc.query = query
    doc.chart_type = chart_type
    doc.is_standard = 0
    doc.visibility = "Everyone"
    doc.sort_order = sort_order
    doc.config = json.dumps(config)
    doc.save(ignore_permissions=True)
    return doc.name


def _axis(chart_kind, x_column, x_type, y_column, y_label, ranked=False):
    series = {
        "name": y_label,
        "type": "line" if chart_kind == "Line" else "bar",
        "measure": _measure(y_column),
        "color": ["#1a73e8"],
    }
    if chart_kind == "Line":
        series["smooth"] = True
        series["show_area"] = True
    config = {
        "x_axis": {"dimension": _dimension(x_column, x_type)},
        "y_axis": {"series": [series], "show_data_labels": chart_kind != "Line"},
    }
    if ranked:
        config["order_by"] = [{"column": {"column_name": y_column}, "direction": "desc"}]
    return config


def _day_spine(days):
    selects = " UNION ALL ".join(f"SELECT {offset} AS seq" for offset in range(days))
    return (
        "SELECT DATE_SUB(CURDATE(), INTERVAL seq DAY) AS day "
        f"FROM ({selects}) days"
    )


def _layout_items(cards, charts):
    items = []
    for index, chart in enumerate(cards):
        items.append(
            {
                "type": "chart",
                "chart": chart,
                "layout": {
                    "i": frappe.generate_hash(length=8),
                    "x": index * 5,
                    "y": 0,
                    "w": 5,
                    "h": 4,
                },
            }
        )
    y = 4
    pending_side = None
    for kind, chart in charts:
        if kind == "wide":
            items.append(
                {
                    "type": "chart",
                    "chart": chart,
                    "layout": {"i": frappe.generate_hash(length=8), "x": 0, "y": y, "w": 20, "h": 14},
                }
            )
            y += 14
        elif kind == "main":
            items.append(
                {
                    "type": "chart",
                    "chart": chart,
                    "layout": {"i": frappe.generate_hash(length=8), "x": 0, "y": y, "w": 13, "h": 16},
                }
            )
            pending_side = y
        elif kind == "side":
            side_y = pending_side if pending_side is not None else y
            items.append(
                {
                    "type": "chart",
                    "chart": chart,
                    "layout": {"i": frappe.generate_hash(length=8), "x": 13, "y": side_y, "w": 7, "h": 16},
                }
            )
            if pending_side is not None:
                y = pending_side + 16
                pending_side = None
            else:
                y += 16
    return items


def _check_charts(dashboard_name, items):
    checks = []
    for item in items:
        chart = frappe.get_doc("Insights Chart v3", item["chart"])
        try:
            result = chart.fetch(force=True)
            rows = result.get("rows") or []
            checks.append(
                {
                    "chart": chart.name,
                    "title": chart.title,
                    "type": chart.chart_type,
                    "rows": len(rows),
                    "columns": [column.get("name") for column in (result.get("columns") or [])],
                    "sample": rows[:1],
                }
            )
        except Exception as exc:
            checks.append(
                {
                    "chart": chart.name,
                    "title": chart.title,
                    "type": chart.chart_type,
                    "error": str(exc),
                }
            )
    print(json.dumps({"dashboard": dashboard_name, "charts": checks}, default=str))


def _number(column_name):
    return {
        "sparkline": False,
        "number_column_options": [],
        "number_columns": [{**_measure(column_name), "id": column_name}],
    }


def restyle_website():
    """Turn the website workbook into a Google Analytics style dashboard."""
    frappe.set_user("Administrator")
    frappe.reload_doc("insights", "doctype", "insights_chart_v3", force=True)
    frappe.reload_doc("insights", "doctype", "insights_dashboard_v3", force=True)
    source = _site_source()
    workbook = _workbook("Website stats")
    _share_workbook(workbook)

    totals = []
    if _table_exists("tabWeb Page View"):
        totals.append(
            (
                "Views, 30 days",
                "Views",
                """
                SELECT COUNT(*) AS `Views`
                FROM `tabWeb Page View`
                WHERE creation >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
                """,
            )
        )
    if _table_exists("tabWeb Page"):
        totals.append(
            (
                "Pages",
                "Pages",
                """
                SELECT COUNT(*) AS `Pages`
                FROM `tabWeb Page`
                """,
            )
        )
    if _table_exists("tabBlog Post"):
        totals.append(
            (
                "Posts",
                "Posts",
                """
                SELECT COUNT(*) AS `Posts`
                FROM `tabBlog Post`
                WHERE published = 1
                """,
            )
        )
    if _table_exists("tabWeb Page View"):
        totals.append(
            (
                "Paths viewed",
                "Paths",
                """
                SELECT COUNT(DISTINCT path) AS `Paths`
                FROM `tabWeb Page View`
                WHERE creation >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
                """,
            )
        )

    cards = []
    for index, (title, column, sql) in enumerate(totals):
        query = _native_query(workbook, title, source, sql, 100 + index)
        cards.append(_set_chart(workbook, title, query, "Number", _number(column), 100 + index))

    charts = []
    if _table_exists("tabWeb Page View"):
        daily = _native_query(
            workbook,
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
        charts.append(
            (
                "wide",
                _set_chart(
                    workbook,
                    "Page views by day",
                    daily,
                    "Line",
                    _axis("Line", "day", "Date", "views", "Views"),
                    1,
                ),
            )
        )
        by_path = _native_query(
            workbook,
            "Page views by path",
            source,
            """
            SELECT path, COUNT(*) AS views
            FROM `tabWeb Page View`
            WHERE creation >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            GROUP BY path
            ORDER BY views DESC
            LIMIT 15
            """,
            0,
        )
        charts.append(
            (
                "main",
                _set_chart(
                    workbook,
                    "Page views by path",
                    by_path,
                    "Row",
                    _axis("Bar", "path", "String", "views", "Views", ranked=True),
                    0,
                ),
            )
        )
        browsers = _native_query(
            workbook,
            "Browsers",
            source,
            """
            SELECT IFNULL(NULLIF(browser, ''), 'Unknown') AS browser, COUNT(*) AS views
            FROM `tabWeb Page View`
            WHERE creation >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            GROUP BY browser
            ORDER BY views DESC
            """,
            3,
        )
        charts.append(
            (
                "side",
                _set_chart(
                    workbook,
                    "Browsers",
                    browsers,
                    "Donut",
                    {
                        "label_column": _dimension("browser"),
                        "value_column": _measure("views"),
                        "show_inline_labels": True,
                    },
                    3,
                ),
            )
        )
        sources_query = _native_query(
            workbook,
            "Traffic sources",
            source,
            """
            SELECT CASE
                WHEN referrer IS NULL OR referrer = '' THEN 'Direct'
                WHEN referrer LIKE '%google.%' THEN 'Google'
                WHEN referrer LIKE '%bing.%' THEN 'Bing'
                WHEN referrer LIKE '%yahoo.%' THEN 'Yahoo'
                WHEN referrer LIKE '%duckduckgo.%' THEN 'DuckDuckGo'
                WHEN referrer LIKE '%facebook.%' OR referrer LIKE '%instagram.%'
                    OR referrer LIKE '%linkedin.%' OR referrer LIKE '%t.co%' THEN 'Social'
                WHEN referrer LIKE '%tgipower.com%' THEN 'tgipower.com'
                ELSE 'Other'
            END AS channel, COUNT(*) AS views
            FROM `tabWeb Page View`
            WHERE creation >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            GROUP BY 1
            ORDER BY views DESC
            """,
            2,
        )
        charts.append(
            (
                "wide",
                _set_chart(
                    workbook,
                    "Traffic sources",
                    sources_query,
                    "Bar",
                    _axis("Bar", "channel", "String", "views", "Views", ranked=True),
                    2,
                ),
            )
        )

    items = []
    for index, chart in enumerate(cards):
        items.append(
            {
                "type": "chart",
                "chart": chart,
                "layout": {
                    "i": frappe.generate_hash(length=8),
                    "x": index * 5,
                    "y": 0,
                    "w": 5,
                    "h": 4,
                },
            }
        )
    y = 4
    pending_side = None
    for kind, chart in charts:
        if kind == "wide":
            items.append(
                {
                    "type": "chart",
                    "chart": chart,
                    "layout": {"i": frappe.generate_hash(length=8), "x": 0, "y": y, "w": 20, "h": 14},
                }
            )
            y += 14
        elif kind == "main":
            items.append(
                {
                    "type": "chart",
                    "chart": chart,
                    "layout": {"i": frappe.generate_hash(length=8), "x": 0, "y": y, "w": 13, "h": 16},
                }
            )
            pending_side = y
        elif kind == "side":
            side_y = pending_side if pending_side is not None else y
            items.append(
                {
                    "type": "chart",
                    "chart": chart,
                    "layout": {"i": frappe.generate_hash(length=8), "x": 13, "y": side_y, "w": 7, "h": 16},
                }
            )
            if pending_side is not None:
                y = pending_side + 16
                pending_side = None
            else:
                y += 16
    if pending_side is not None:
        y = pending_side + 16

    dashboard = _dashboard(workbook, "Website stats", [])
    doc = frappe.get_doc("Insights Dashboard v3", dashboard)
    doc.visibility = "Everyone"
    doc.items = items
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    checks = []
    for item in items:
        chart = frappe.get_doc("Insights Chart v3", item["chart"])
        try:
            result = chart.fetch(force=True)
            rows = result.get("rows") or []
            checks.append(
                {
                    "chart": chart.name,
                    "title": chart.title,
                    "type": chart.chart_type,
                    "rows": len(rows),
                    "columns": [column.get("name") for column in (result.get("columns") or [])],
                    "sample": rows[:1],
                }
            )
        except Exception as exc:
            checks.append(
                {
                    "chart": chart.name,
                    "title": chart.title,
                    "type": chart.chart_type,
                    "error": str(exc),
                }
            )
    print(json.dumps({"dashboard": doc.name, "charts": checks}, default=str))
    return doc.name


def restyle_users():
    """Turn the user workbook into summary numbers plus login charts."""
    frappe.set_user("Administrator")
    frappe.reload_doc("insights", "doctype", "insights_chart_v3", force=True)
    frappe.reload_doc("insights", "doctype", "insights_dashboard_v3", force=True)
    source = _site_source()
    workbook = _workbook("User stats")
    _share_workbook(workbook)
    accounts = "name NOT IN ('Guest', 'Administrator')"

    totals = [
        (
            "Users",
            "Users",
            f"""
            SELECT COUNT(*) AS `Users`
            FROM tabUser
            WHERE {accounts}
            """,
        ),
        (
            "Enabled",
            "Enabled",
            f"""
            SELECT COUNT(*) AS `Enabled`
            FROM tabUser
            WHERE {accounts}
              AND enabled = 1
            """,
        ),
    ]
    if _table_exists("tabActivity Log"):
        totals.extend(
            [
                (
                    "Logins, 30 days",
                    "Logins",
                    """
                    SELECT COUNT(*) AS `Logins`
                    FROM `tabActivity Log`
                    WHERE operation = 'Login'
                      AND creation >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
                    """,
                ),
                (
                    "Signed in",
                    "People",
                    """
                    SELECT COUNT(DISTINCT user) AS `People`
                    FROM `tabActivity Log`
                    WHERE operation = 'Login'
                      AND creation >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
                      AND user NOT IN ('Guest', 'Administrator', 'Unknown User')
                    """,
                ),
            ]
        )

    cards = []
    for index, (title, column, sql) in enumerate(totals):
        query = _native_query(workbook, title, source, sql, 100 + index)
        cards.append(_set_chart(workbook, title, query, "Number", _number(column), 100 + index))

    charts = []
    if _table_exists("tabActivity Log"):
        daily = _native_query(
            workbook,
            "Logins by day",
            source,
            f"""
            SELECT days.day, COUNT(log.name) AS logins
            FROM ({_day_spine(30)}) days
            LEFT JOIN `tabActivity Log` log
              ON log.operation = 'Login'
             AND DATE(log.creation) = days.day
            GROUP BY days.day
            ORDER BY days.day
            """,
            1,
        )
        charts.append(
            (
                "wide",
                _set_chart(
                    workbook,
                    "Logins by day",
                    daily,
                    "Line",
                    _axis("Line", "day", "Date", "logins", "Logins"),
                    1,
                ),
            )
        )
        by_person = _native_query(
            workbook,
            "Logins by person",
            source,
            """
            SELECT user AS person, COUNT(*) AS logins
            FROM `tabActivity Log`
            WHERE operation = 'Login'
              AND creation >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
              AND user NOT IN ('Guest', 'Administrator')
            GROUP BY user
            ORDER BY logins DESC
            LIMIT 12
            """,
            0,
        )
        charts.append(
            (
                "main",
                _set_chart(
                    workbook,
                    "Logins by person",
                    by_person,
                    "Row",
                    _axis("Bar", "person", "String", "logins", "Logins", ranked=True),
                    0,
                ),
            )
        )
    seen = _native_query(
        workbook,
        "Last seen",
        source,
        f"""
        SELECT CASE
            WHEN last_login IS NULL THEN 'Never'
            WHEN last_login >= DATE_SUB(CURDATE(), INTERVAL 7 DAY) THEN 'This week'
            WHEN last_login >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) THEN 'This month'
            ELSE 'Older'
        END AS seen, COUNT(*) AS users
        FROM tabUser
        WHERE {accounts}
        GROUP BY 1
        ORDER BY users DESC
        """,
        3,
    )
    charts.append(
        (
            "side",
            _set_chart(
                workbook,
                "Last seen",
                seen,
                "Donut",
                {
                    "label_column": _dimension("seen"),
                    "value_column": _measure("users"),
                    "show_inline_labels": True,
                },
                3,
            ),
        )
    )
    if _table_exists("tabHas Role"):
        roles = _native_query(
            workbook,
            "Users by role",
            source,
            f"""
            SELECT role, COUNT(DISTINCT parent) AS users
            FROM `tabHas Role`
            WHERE parenttype = 'User'
              AND parent NOT IN ('Guest', 'Administrator')
            GROUP BY role
            ORDER BY users DESC
            LIMIT 12
            """,
            2,
        )
        charts.append(
            (
                "wide",
                _set_chart(
                    workbook,
                    "Users by role",
                    roles,
                    "Bar",
                    _axis("Bar", "role", "String", "users", "Users", ranked=True),
                    2,
                ),
            )
        )

    items = _layout_items(cards, charts)
    dashboard = _dashboard(workbook, "User stats", [])
    doc = frappe.get_doc("Insights Dashboard v3", dashboard)
    doc.visibility = "Everyone"
    doc.items = items
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    _check_charts(doc.name, items)
    return doc.name


if __name__ == "__main__":
    frappe.init(site="erp.tspgusa.com", sites_path="/home/frappe/frappe-bench/sites")
    frappe.connect()
    try:
        run()
    finally:
        frappe.destroy()
