import re

with open('frontend/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('ipo.ipo_id', 'ipo.id')
content = content.replace('ipo.ipo_type', 'ipo.segment')

content = re.sub(
    r"let gmpStr = '--';.*?\}",
    "let gmpStr = '--';\n                    let estListingStr = '--';\n                    if (ipo.gmp) {\n                        gmpStr = `₹${ipo.gmp} (${ipo.estimated_listing_gain_pct?.toFixed(2) || 0}%)`;\n                        estListingStr = `₹${ipo.estimated_listing_price?.toFixed(2) || '--'}`;\n                    }",
    content,
    flags=re.DOTALL,
    count=1
)

content = re.sub(
    r"let subStr = '--';.*?\}",
    "let subStr = '--';\n                    if (ipo.total_subscription) {\n                        subStr = `${ipo.total_subscription?.toFixed(2)}x`;\n                    }",
    content,
    flags=re.DOTALL,
    count=1
)

content = re.sub(
    r"let issueSizeStr = ipo\.total_issue_size.*?;",
    "let issueSizeStr = ipo.issue_size_crore ? `₹${ipo.issue_size_crore.toFixed(2)} Cr` : '--';",
    content,
    count=1
)

with open('frontend/index.html', 'w', encoding='utf-8') as f:
    f.write(content)
