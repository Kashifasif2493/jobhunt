import os
import requests
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

REMOTIVE_API = "https://remotive.com/api/remote-jobs"

CATEGORIES = [
    "All", "Software Development", "Customer Service", "Design",
    "Marketing", "Sales", "Data", "DevOps / Sysadmin",
    "Finance / Legal", "Product", "Writing", "HR", "Hotel Management",
]

@app.route('/')
def index():
    return render_template("index.html", categories=CATEGORIES)

@app.route('/about')
def about():
    return render_template("about.html")

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    success = False
    if request.method == 'POST':
        success = True
    return render_template("contact.html", success=success)

@app.route('/privacy')
def privacy():
    return render_template("privacy.html")


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

@app.route('/terms')
def terms():
    return render_template("terms.html")

@app.route('/disclaimer')
def disclaimer():
    return render_template("disclaimer.html")

@app.route('/api/jobs')
def get_jobs():
    category = request.args.get('category', '')
    search   = request.args.get('search', '').strip()
    country  = request.args.get('country', '').strip().lower()

    all_jobs = []
    seen_ids = set()

    def add_jobs(jobs):
        for j in jobs:
            jid = j.get('id')
            if jid not in seen_ids:
                seen_ids.add(jid)
                all_jobs.append(j)

    if category == 'Hotel Management':
        try:
            r = requests.get(REMOTIVE_API, timeout=10)
            jobs = r.json().get('jobs', [])
            hotel_kw = ['hotel', 'hospitality', 'restaurant', 'food', 'beverage',
                       'chef', 'cook', 'housekeeping', 'front desk', 'concierge',
                       'catering', 'resort', 'tourism', 'travel']
            jobs = [j for j in jobs if any(kw in (j.get('title','') + j.get('description','')).lower() for kw in hotel_kw)]
            add_jobs(jobs)
        except:
            pass
    elif category and category != 'All':
        try:
            r = requests.get(REMOTIVE_API, params={'category': category}, timeout=10)
            add_jobs(r.json().get('jobs', []))
        except:
            pass
    else:
        cats = ['software-dev','customer-support','design','marketing','sales',
                'data','devops','finance-legal','product','writing','hr',
                'qa','teaching','medical','legal','business','management','operations']
        for cat in cats:
            try:
                r = requests.get(REMOTIVE_API, params={'category': cat}, timeout=8)
                add_jobs(r.json().get('jobs', []))
            except:
                continue
        try:
            r = requests.get(REMOTIVE_API, timeout=10)
            add_jobs(r.json().get('jobs', []))
        except:
            pass

    # Filter by search
    if search:
        kw = search.lower()
        all_jobs = [j for j in all_jobs if kw in j.get('title','').lower()
                   or kw in j.get('company_name','').lower()
                   or kw in j.get('description','').lower()]

    # Filter by country
    if country:
        if country == 'usa':
            all_jobs = [j for j in all_jobs if any(kw in (j.get('candidate_required_location') or '').lower() for kw in ['usa','united states','us ','america','u.s'])]
        elif country == 'uk':
            all_jobs = [j for j in all_jobs if any(kw in (j.get('candidate_required_location') or '').lower() for kw in ['uk','united kingdom','britain','england'])]
        elif country in ['uae','dubai']:
            all_jobs = [j for j in all_jobs if any(kw in (j.get('candidate_required_location') or '').lower() for kw in ['uae','dubai','emirates','abu dhabi'])]
        elif country == 'india':
            all_jobs = [j for j in all_jobs if any(kw in (j.get('candidate_required_location') or '').lower() for kw in ['india','bangalore','mumbai','delhi','hyderabad','chennai','pune'])]
        elif country == 'pakistan':
            all_jobs = [j for j in all_jobs if any(kw in (j.get('candidate_required_location') or '').lower() for kw in ['pakistan','karachi','lahore','islamabad','worldwide','remote','anywhere'])]
        elif country == 'canada':
            all_jobs = [j for j in all_jobs if any(kw in (j.get('candidate_required_location') or '').lower() for kw in ['canada','toronto','vancouver','montreal'])]
        elif country == 'australia':
            all_jobs = [j for j in all_jobs if any(kw in (j.get('candidate_required_location') or '').lower() for kw in ['australia','sydney','melbourne','brisbane'])]
        elif country == 'germany':
            all_jobs = [j for j in all_jobs if any(kw in (j.get('candidate_required_location') or '').lower() for kw in ['germany','berlin','munich','hamburg','europe'])]
        elif country == 'europe':
            all_jobs = [j for j in all_jobs if any(kw in (j.get('candidate_required_location') or '').lower() for kw in ['europe','eu','european'])]
        elif country == 'asia':
            all_jobs = [j for j in all_jobs if any(kw in (j.get('candidate_required_location') or '').lower() for kw in ['asia','asian','india','pakistan','singapore','japan'])]
        elif country == 'remote':
            all_jobs = [j for j in all_jobs if any(kw in (j.get('candidate_required_location') or '').lower() for kw in ['remote','worldwide','anywhere','global'])]
        else:
            all_jobs = [j for j in all_jobs if country in (j.get('candidate_required_location') or '').lower()]

    result = [{
        'id':       j.get('id'),
        'title':    j.get('title') or 'Job Opening',
        'company':  j.get('company_name') or 'Company',
        'logo':     j.get('company_logo') or '',
        'category': j.get('category') or category or 'General',
        'job_type': j.get('job_type') or 'Full Time',
        'location': j.get('candidate_required_location') or 'Worldwide',
        'salary':   j.get('salary') or '',
        'url':      j.get('url') or '#',
        'posted':   (j.get('publication_date') or '')[:10],
        'tags':     (j.get('tags') or [])[:4],
    } for j in all_jobs]

    # Sort newest first
    result.sort(key=lambda x: x.get('posted', ''), reverse=True)

    return jsonify({'jobs': result, 'total': len(result)})


@app.route('/sitemap.xml')
def sitemap():
    pages = [
        '/', '/about', '/contact', '/blog', '/privacy', '/terms', '/disclaimer',
        '/blog/how-to-write-a-resume', '/blog/remote-job-tips', '/blog/interview-tips',
        '/blog/linkedin-profile-tips', '/blog/cover-letter-guide', '/blog/salary-negotiation',
        '/blog/best-remote-jobs-for-beginners', '/blog/how-to-make-a-professional-cv',
        '/blog/top-freelance-skills-2026', '/blog/how-to-prepare-for-online-interviews',
        '/blog/best-websites-to-find-remote-jobs'
    ]
    xml = '<?xml version="1.0" encoding="UTF-8"?>'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    for page in pages:
        xml += f'<url><loc>https://worldjobshunt.com{page}</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>'
    xml += '</urlset>'
    from flask import Response
    return Response(xml, mimetype='application/xml')

@app.route('/robots.txt')
def robots():
    from flask import Response
    txt = "User-agent: *\nAllow: /\nSitemap: https://worldjobshunt.com/sitemap.xml"
    return Response(txt, mimetype='text/plain')

if __name__ == '__main__':
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug, port=5000)
