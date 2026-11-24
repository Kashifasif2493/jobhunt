import os
import re
import time
import html as html_lib
import threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

import requests
from flask import Flask, render_template, request, jsonify, Response, url_for, redirect

app = Flask(__name__)

# =========================
# JOB SOURCES
# =========================
# Jobs come from four public job feeds. Each one asks for credit and a link
# back to the original posting, which the site shows on every job card:
#   Remotive  - remotive.com  (small public sample, asks for ~4 fetches a day)
#   Jobicy    - jobicy.com    (fair use: credit Jobicy, poll at most once an hour)
#   Remote OK - remoteok.com  (link back to the job on Remote OK and name it)
#   Arbeitnow - arbeitnow.com (link back to Arbeitnow; only remote jobs are used)
# Every source is cached for 6 hours. If one source fails, the others keep
# working and the last good data for that source is kept.

REMOTIVE_API = "https://remotive.com/api/remote-jobs"
JOBICY_API = "https://jobicy.com/api/v2/remote-jobs"
REMOTEOK_API = "https://remoteok.com/api"
ARBEITNOW_API = "https://www.arbeitnow.com/api/job-board-api"

HTTP_HEADERS = {
    "User-Agent": "WorldJobShunt/1.0 (+https://worldjobshunt.com)",
    "Accept": "application/json",
}
HTTP_TIMEOUT = 10

CACHE_TTL_SECONDS = 6 * 60 * 60        # refresh each source at most every 6 hours
RETRY_AFTER_FAILURE_SECONDS = 15 * 60  # wait 15 minutes after a failed fetch


def _clean_text(value, limit=1500):
    """Plain text from an HTML description (used for keyword search)."""
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _iso_date(value):
    """Return an ISO date string that starts with YYYY-MM-DD, or ''."""
    if isinstance(value, (int, float)) and value > 0:
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
        except Exception:
            return ""
    if isinstance(value, str) and re.match(r"\d{4}-\d{2}-\d{2}", value):
        return value
    return ""


def _job_type(value):
    if isinstance(value, list):
        value = value[0] if value else ""
    value = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return value or "full_time"


def _money(min_v, max_v, currency, period):
    try:
        if not (min_v and max_v and currency):
            return ""
        if int(min_v) == int(max_v):
            return f"{currency} {int(min_v):,}/{period or 'yearly'}"
        return f"{currency} {int(min_v):,}-{int(max_v):,}/{period or 'yearly'}"
    except Exception:
        return ""


# Map each source's own category / title words onto the site's category pills,
# so the category filter works for every source.
CATEGORY_RULES = [
    ("Customer Service", ["customer", "support", "helpdesk", "help desk"]),
    ("DevOps / Sysadmin", ["devops", "sysadmin", "sre", "infrastructure", "site reliability", "cloud engineer", "platform engineer"]),
    ("Data", ["data", "analytics", "analyst", "machine learning", "scientist"]),
    ("Software Development", ["software", "developer", "engineer", "engineering", "programmer", "frontend", "front-end", "backend", "back-end", "full stack", "full-stack", "mobile", "android", "ios "]),
    ("Design", ["design", "ux", "creative", "graphic", "illustrat", "animation"]),
    ("Marketing", ["marketing", "seo", "growth", "social media", "community", "brand", "advertis"]),
    ("Sales", ["sales", "account executive", "business development", "account manager"]),
    ("Finance / Legal", ["finance", "accounting", "accountant", "legal", "lawyer", "tax", "payroll", "bookkeep", "compliance", "audit"]),
    ("Product", ["product"]),
    ("Writing", ["writer", "writing", "copywrit", "editor", "content", "translat"]),
    ("HR", ["recruit", "talent", "human resources", "people ops", "people partner", "hr "]),
]

# The "HR" pill must also match Remotive's own "Human Resources" category.
CATEGORY_ALIASES = {"hr": ["hr", "human resources"]}


def guess_category(raw, title, tags):
    for text in (raw, title, " ".join(tags or [])):
        text = f" {text or ''} ".lower()
        for label, words in CATEGORY_RULES:
            if any(w in text for w in words):
                return label
    return (raw or "").strip() or "General"


def fetch_remotive():
    r = requests.get(REMOTIVE_API, headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    jobs = r.json().get("jobs", [])
    for j in jobs:
        j["source"] = "Remotive"
    return jobs


def fetch_jobicy():
    r = requests.get(JOBICY_API, params={"count": 200}, headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        title = j.get("jobTitle") or ""
        industries = j.get("jobIndustry") or []
        if isinstance(industries, str):
            industries = [industries]
        if not title or not j.get("url"):
            continue
        out.append({
            "id": f"jobicy-{j.get('id')}",
            "title": title,
            "company_name": j.get("companyName") or "",
            "company_logo": j.get("companyLogo") or "",
            "category": guess_category(" ".join(industries), title, []),
            "job_type": _job_type(j.get("jobType")),
            "candidate_required_location": j.get("jobGeo") or "Anywhere",
            "salary": _money(j.get("salaryMin"), j.get("salaryMax"), j.get("salaryCurrency"), j.get("salaryPeriod")),
            "url": j.get("url"),
            "publication_date": _iso_date(j.get("pubDate")),
            "tags": [],
            "description": _clean_text(j.get("jobExcerpt")),
            "source": "Jobicy",
        })
    return out


def fetch_remoteok():
    r = requests.get(REMOTEOK_API, headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json():
        # the first item in the feed is a legal notice, not a job
        if not isinstance(j, dict) or not j.get("position") or not j.get("url"):
            continue
        tags = [t for t in (j.get("tags") or []) if isinstance(t, str)]
        mn, mx = j.get("salary_min"), j.get("salary_max")
        period = "hourly" if (mx and mx <= 500) else "yearly"
        out.append({
            "id": f"remoteok-{j.get('id')}",
            "title": j.get("position"),
            "company_name": j.get("company") or "",
            "company_logo": j.get("company_logo") or j.get("logo") or "",
            "category": guess_category("", j.get("position"), tags),
            "job_type": "full_time",
            "candidate_required_location": (j.get("location") or "").strip() or "Worldwide",
            "salary": _money(mn, mx, "USD", period),
            "url": j.get("url"),
            "publication_date": _iso_date(j.get("date") or j.get("epoch")),
            "tags": tags,
            "description": _clean_text(j.get("description")),
            "source": "Remote OK",
        })
    return out


def fetch_arbeitnow():
    out = []
    for page in (1, 2, 3):
        r = requests.get(ARBEITNOW_API, params={"page": page}, headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        for j in r.json().get("data", []):
            if not j.get("remote") or not j.get("title") or not j.get("url"):
                continue
            tags = [t for t in (j.get("tags") or []) if isinstance(t, str)]
            where = (j.get("location") or "").strip()
            out.append({
                "id": f"arbeitnow-{j.get('slug')}",
                "title": j.get("title"),
                "company_name": j.get("company_name") or "",
                "company_logo": "",
                "category": guess_category("", j.get("title"), tags),
                "job_type": _job_type(j.get("job_types")),
                "candidate_required_location": f"Remote, {where}" if where else "Remote, Europe",
                "salary": "",
                "url": j.get("url"),
                "publication_date": _iso_date(j.get("created_at")),
                "tags": tags,
                "description": _clean_text(j.get("description")),
                "source": "Arbeitnow",
            })
    return out


SOURCES = {
    "Remotive": fetch_remotive,
    "Jobicy": fetch_jobicy,
    "Remote OK": fetch_remoteok,
    "Arbeitnow": fetch_arbeitnow,
}

_state = {name: {"data": [], "fetched_at": 0, "last_attempt": 0} for name in SOURCES}
_refresh_lock = threading.Lock()


def _due_sources(now):
    due = []
    for name, st in _state.items():
        is_old = (now - st["fetched_at"]) > CACHE_TTL_SECONDS
        can_try = (now - st["last_attempt"]) > RETRY_AFTER_FAILURE_SECONDS
        if (not st["data"] or is_old) and can_try:
            due.append(name)
    return due


def _refresh_source(name):
    st = _state[name]
    st["last_attempt"] = time.time()
    try:
        jobs = SOURCES[name]()
        if jobs:
            st["data"] = jobs
            st["fetched_at"] = time.time()
    except Exception:
        pass  # keep the last good data for this source


def _combined_jobs():
    seen, merged = set(), []
    for name in SOURCES:
        for j in _state[name]["data"]:
            key = ((j.get("title") or "").strip().lower(), (j.get("company_name") or "").strip().lower())
            if key in seen:
                continue
            seen.add(key)
            merged.append(j)
    return merged


def get_cached_jobs():
    if _due_sources(time.time()):
        have_data = any(st["data"] for st in _state.values())
        # First load (no data yet): wait for the refresh. Later: if another
        # visitor is already refreshing, just serve what we have.
        if _refresh_lock.acquire(blocking=not have_data):
            try:
                due = _due_sources(time.time())
                if due:
                    with ThreadPoolExecutor(max_workers=len(due)) as pool:
                        list(pool.map(_refresh_source, due))
            finally:
                _refresh_lock.release()
    return _combined_jobs()

CATEGORIES = [
    "All",
    "Software Development",
    "Customer Service",
    "Design",
    "Marketing",
    "Sales",
    "Data",
    "DevOps / Sysadmin",
    "Finance / Legal",
    "Product",
    "Writing",
    "HR",
    "Hotel Management",
]

# =========================
# MAIN PAGES
# =========================

MAX_PER_COMPANY = 3      # job list: at most this many jobs per company (not applied to searches)
HOMEPAGE_JOBS = 10       # jobs drawn on the server so the homepage is not empty for search engines


def _public_job(j):
    """The job fields that the website (and /api/jobs) shows."""
    return {
        'id': j.get('id'),
        'title': j.get('title') or 'Job Opening',
        'company': j.get('company_name') or 'Company',
        'logo': j.get('company_logo') or '',
        'category': j.get('category') or 'General',
        'job_type': j.get('job_type') or 'Full Time',
        'location': j.get('candidate_required_location') or 'Worldwide',
        'salary': j.get('salary') or '',
        'url': j.get('url') or '#',
        'posted': (j.get('publication_date') or '')[:10],
        'tags': (j.get('tags') or [])[:4],
        'source': j.get('source') or 'Remotive',
    }


def _time_ago(date_str):
    try:
        days = (datetime.now(timezone.utc).date() - datetime.strptime(date_str[:10], "%Y-%m-%d").date()).days
    except Exception:
        return ""
    if days <= 0:
        return "Today"
    if days == 1:
        return "1 day ago"
    if days < 30:
        return f"{days} days ago"
    return f"{days // 30} month(s) ago"


def _refresh_in_background():
    """Start a refresh without making the visitor wait for it."""
    if _due_sources(time.time()) and not _refresh_lock.locked():
        threading.Thread(target=get_cached_jobs, daemon=True).start()


@app.route('/')
def index():
    _refresh_in_background()
    jobs = sorted(_combined_jobs(), key=lambda j: j.get('publication_date') or '', reverse=True)
    featured, seen = [], set()
    for j in jobs:
        company = (j.get('company_name') or '').strip().lower()
        if company in seen:
            continue            # one job per company on the first screen
        seen.add(company)
        pj = _public_job(j)
        pj['salary_short'] = _clean_text(pj['salary'], 28)
        pj['ago'] = _time_ago(pj['posted'])
        featured.append(pj)
        if len(featured) >= HOMEPAGE_JOBS:
            break
    return render_template("index.html", categories=CATEGORIES, featured=featured)

@app.route('/search')
def search():
    return render_template("search.html")
@app.route('/about')
def about():
    return render_template("about.html")

@app.route('/contact')
def contact():
    return render_template("contact.html")

@app.route('/privacy')
def privacy():
    return render_template("privacy.html")

@app.route('/terms')
def terms():
    return render_template("terms.html")

@app.route('/disclaimer')
def disclaimer():
    return render_template("disclaimer.html")

@app.route('/faq')
def faq():
    return render_template("faq.html")

@app.route('/resources')
def resources():
    return render_template("resources.html")

@app.route('/promptvault')
def promptvault():
    return render_template("promptvault.html")

@app.route('/legal-information')
def legal_information():
    return render_template("legal_information.html")

# =========================
# BLOG PAGES
# =========================

@app.route('/blog')
def blog():
    return render_template("blog.html")

@app.route('/blog/how-to-write-a-resume')
def blog_resume():
    return render_template("blog_resume.html")

@app.route('/blog/remote-job-tips')
def blog_remote():
    return render_template("blog_remote.html")

@app.route('/blog/interview-tips')
def blog_interview():
    return render_template("blog_interview.html")

@app.route('/blog/linkedin-profile-tips')
def blog_linkedin():
    return render_template("blog_linkedin.html")

@app.route('/blog/cover-letter-guide')
def blog_coverletter():
    return render_template("blog_coverletter.html")

@app.route('/blog/salary-negotiation')
def blog_salary():
    return render_template("blog_salary.html")

@app.route('/blog/best-remote-jobs-for-beginners')
def blog_beginners():
    return render_template("blog_beginners.html")

@app.route('/blog/how-to-make-a-professional-cv')
def blog_cv():
    return render_template("blog_cv.html")

@app.route('/blog/top-freelance-skills-2026')
def blog_freelance():
    return render_template("blog_freelance.html")

@app.route('/blog/how-to-prepare-for-online-interviews')
def blog_online_interview():
    return render_template("blog_online_interview.html")

@app.route('/blog/best-websites-to-find-remote-jobs')
def blog_job_sites():
    return render_template("blog_job_sites.html")

@app.route('/blog/latest-remote-jobs-for-beginners-2026')
def blog_remote_2026():
    # This guide was merged into "Best Remote Jobs for Beginners" (same topic, same jobs).
    return redirect(url_for('blog_beginners'), code=301)

@app.route('/blog/best-remote-job-boards-in-2026')
def blog_remote_boards_2026():
    return render_template("blog_remote_boards_2026.html")
@app.route('/blog/best-remote-job-boards-2026')
def blog_remote_boards_old():
    return redirect(
        url_for('blog_remote_boards_2026'),
        code=301
    )
@app.route('/blog/best-remote-job-search-engines-2026')
def blog_remote_search_2026():
    return render_template("blog_remote_search_2026.html")

@app.route('/blog/legit-work-from-home-jobs-2026')
def blog_work_from_home_2026():
    return render_template("blog_work_from_home_2026.html")

@app.route('/blog/best-remote-job-sites-2026')
def blog_remote_job_sites_2026():
    return render_template("blog_remote_job_sites_2026.html")

@app.route('/blog/best-ai-tools-for-job-seekers-2026')
def blog_ai_tools_2026():
    return render_template("blog_ai_tools_2026.html")

@app.route('/blog/how-to-negotiate-salary-2026')
def blog_salary_negotiation_2026():
    return render_template("blog_salary_negotiation_2026.html")

@app.route('/blog/best-ai-resume-builders-2026')
def blog_ai_resume_builders_2026():
    return render_template("blog_ai_resume_builders_2026.html")

@app.route('/blog/top-remote-companies-hiring-2026')
def blog_remote_companies_2026():
    return render_template("blog_remote_companies_2026.html")

@app.route('/blog/best-side-hustles-from-home-2026')
def blog_side_hustles_2026():
    return render_template("blog_side_hustles_2026.html")

@app.route('/blog/how-to-receive-international-payments-pakistan-2026')
def blog_international_payments_2026():
    return render_template("blog_international_payments_2026.html")

@app.route('/blog/kickresume-review-2026')
def blog_kickresume_review_2026():
    return render_template("blog_kickresume_review_2026.html")

@app.route('/blog/companies-offering-remote-relocation-2026')
def blog_remote_relocation_2026():
    return render_template("blog_remote_relocation_2026.html")

@app.route('/blog/best-hybrid-companies-hiring-2026')
def blog_hybrid_companies_2026():
    return render_template("blog_hybrid_companies_2026.html")

@app.route('/blog/how-to-avoid-remote-job-scams-2026')
def blog_remote_job_scams_2026():
    return render_template("blog_remote_job_scams_2026.html")

@app.route('/blog/best-remote-work-tools-software-2026')
def blog_remote_work_tools_2026():
    return render_template("blog_remote_work_tools_2026.html")

@app.route('/blog/top-companies-hiring-remote-workers-2026')
def blog_remote_companies_verified_2026():
    return render_template("blog_remote_companies_verified_2026.html")

@app.route('/blog/highest-paying-remote-jobs-no-degree-2026')
def blog_high_paying_remote_no_degree_2026():
    return render_template("blog_high_paying_remote_no_degree_2026.html")

@app.route('/blog/how-to-get-remote-job-no-experience-30-days')
def blog_remote_job_no_experience_30_days():
    return render_template("blog_remote_job_no_experience_30_days.html")

@app.route('/blog/best-entry-level-remote-jobs-for-students-2026')
def blog_entry_level_remote_jobs_students():
    return render_template("blog_entry_level_remote_jobs_students.html")

@app.route('/blog/remote-customer-support-jobs-beginner-guide-2026')
def blog_remote_customer_support_guide():
    return render_template("blog_remote_customer_support_guide.html")

# =========================
# JOB API
# =========================

@app.route('/api/jobs')
def get_jobs():
    category = request.args.get('category', '')
    search = request.args.get('search', '').strip()
    country = request.args.get('country', '').strip().lower()

    all_jobs = []
    seen_ids = set()

    def add_jobs(jobs):
        for j in jobs:
            jid = j.get('id')
            if jid not in seen_ids:
                seen_ids.add(jid)
                all_jobs.append(j)

    add_jobs(get_cached_jobs())

    if category and category not in ("All Categories", "All"):
        needles = CATEGORY_ALIASES.get(category.lower(), [category.lower()])
        all_jobs = [
            j for j in all_jobs
            if any(n in (j.get('category') or '').lower() for n in needles)
        ]
    if search:
        kw = search.lower()
        all_jobs = [j for j in all_jobs if kw in j.get('title', '').lower() or kw in j.get('company_name', '').lower() or kw in j.get('description', '').lower()]

    if country:
        if country == 'usa':
            all_jobs = [j for j in all_jobs if any(kw in (j.get('candidate_required_location') or '').lower() for kw in ['usa', 'united states', 'us ', 'america'])]
        elif country == 'uk':
            all_jobs = [j for j in all_jobs if any(kw in (j.get('candidate_required_location') or '').lower() for kw in ['uk', 'united kingdom', 'britain', 'england'])]
        elif country in ['uae', 'dubai']:
            all_jobs = [j for j in all_jobs if any(kw in (j.get('candidate_required_location') or '').lower() for kw in ['uae', 'dubai', 'emirates'])]
        elif country == 'india':
            all_jobs = [j for j in all_jobs if any(kw in (j.get('candidate_required_location') or '').lower() for kw in ['india', 'bangalore', 'mumbai', 'delhi'])]
        elif country == 'pakistan':
            all_jobs = [j for j in all_jobs if any(kw in (j.get('candidate_required_location') or '').lower() for kw in ['pakistan', 'karachi', 'lahore', 'islamabad', 'worldwide', 'remote', 'anywhere'])]
        elif country == 'canada':
            all_jobs = [j for j in all_jobs if any(kw in (j.get('candidate_required_location') or '').lower() for kw in ['canada', 'toronto', 'vancouver'])]
        elif country == 'australia':
            all_jobs = [j for j in all_jobs if any(kw in (j.get('candidate_required_location') or '').lower() for kw in ['australia', 'sydney', 'melbourne'])]
        elif country == 'germany':
            all_jobs = [j for j in all_jobs if any(kw in (j.get('candidate_required_location') or '').lower() for kw in ['germany', 'berlin', 'europe'])]
        elif country == 'europe':
            all_jobs = [j for j in all_jobs if any(kw in (j.get('candidate_required_location') or '').lower() for kw in ['europe', 'eu', 'european'])]
        elif country == 'asia':
            all_jobs = [j for j in all_jobs if any(kw in (j.get('candidate_required_location') or '').lower() for kw in ['asia', 'india', 'pakistan', 'singapore'])]
        elif country == 'remote':
            all_jobs = [j for j in all_jobs if any(kw in (j.get('candidate_required_location') or '').lower() for kw in ['remote', 'worldwide', 'anywhere'])]
        else:
            all_jobs = [j for j in all_jobs if country in (j.get('candidate_required_location') or '').lower()]

    result = [_public_job(j) for j in all_jobs]

    result.sort(key=lambda x: x.get('posted', ''), reverse=True)
    if not search:
        counts, varied = {}, []
        for x in result:
            key = (x['company'] or '').strip().lower()
            counts[key] = counts.get(key, 0) + 1
            if counts[key] <= MAX_PER_COMPANY:
                varied.append(x)
        result = varied
    result = result[:2000]  # safety limit only; all jobs from the feed are shown
    return jsonify({'jobs': result, 'total': len(result)})


@app.route('/api/stats')
def api_stats():
    jobs = get_cached_jobs()
    companies = {(j.get('company_name') or '').strip().lower() for j in jobs if j.get('company_name')}
    categories = {j.get('category') for j in jobs if j.get('category')}
    return jsonify({
        'jobs': len(jobs),
        'companies': len(companies),
        'categories': len(categories),
        'sources': {name: len(st['data']) for name, st in _state.items()},
    })


# =========================
# SITEMAP
# =========================

@app.route('/sitemap.xml')
def sitemap():
    pages = [
        '/', '/about', '/contact', '/privacy', '/terms', '/disclaimer', '/faq', '/resources', '/promptvault', '/legal-information',
        '/blog',
        '/blog/how-to-write-a-resume',
        '/blog/remote-job-tips',
        '/blog/interview-tips',
        '/blog/linkedin-profile-tips',
        '/blog/cover-letter-guide',
        '/blog/salary-negotiation',
        '/blog/best-remote-jobs-for-beginners',
        '/blog/how-to-make-a-professional-cv',
        '/blog/top-freelance-skills-2026',
        '/blog/how-to-prepare-for-online-interviews',
        '/blog/best-websites-to-find-remote-jobs',
        '/blog/best-remote-job-boards-in-2026',
        '/blog/best-remote-job-search-engines-2026',
        '/blog/legit-work-from-home-jobs-2026',
        '/blog/best-remote-job-sites-2026',
        '/blog/best-ai-tools-for-job-seekers-2026',
        '/blog/how-to-negotiate-salary-2026',
        '/blog/best-ai-resume-builders-2026',
        '/blog/top-remote-companies-hiring-2026',
        '/blog/best-side-hustles-from-home-2026',
        '/blog/top-companies-hiring-remote-workers-2026',
        '/blog/highest-paying-remote-jobs-no-degree-2026',
        '/blog/how-to-get-remote-job-no-experience-30-days',
        '/blog/best-entry-level-remote-jobs-for-students-2026',
        '/blog/remote-customer-support-jobs-beginner-guide-2026',
        '/blog/how-to-receive-international-payments-pakistan-2026',
        '/blog/kickresume-review-2026',
        '/blog/companies-offering-remote-relocation-2026',
        '/blog/best-hybrid-companies-hiring-2026',
        '/blog/how-to-avoid-remote-job-scams-2026',
        '/blog/best-remote-work-tools-software-2026',
    ]

    xml = '<?xml version="1.0" encoding="UTF-8"?>'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    for page in pages:
        xml += f'<url><loc>https://worldjobshunt.com{page}</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>'
    xml += '</urlset>'
    return Response(xml, mimetype='application/xml')


# =========================
# ADS.TXT
# =========================

# =========================
# FAVICON
# =========================

@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('favicon.ico')
@app.route('/ads.txt')
def ads_txt():
    return Response(
        "google.com, pub-9172963361885617, DIRECT, f08c47fec0942fa0",
        mimetype='text/plain'
    )


# =========================
# ROBOTS.TXT
# =========================

@app.route('/robots.txt')
def robots():
    txt = "User-agent: *\nAllow: /\nSitemap: https://worldjobshunt.com/sitemap.xml"
    return Response(txt, mimetype='text/plain')


# =========================
# RUN APP
# =========================

if __name__ == '__main__':
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug, host="0.0.0.0", port=5000)
