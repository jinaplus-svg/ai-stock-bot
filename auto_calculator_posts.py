# -*- coding: utf-8 -*-
"""자취템(soloitems) 블로그에 생활 계산기 포스트를 하나씩 발행하는 자동화.
🌟 [신규] 순수 수학/단위변환 계산기만 다룬다(세금·보험료 등 매년 바뀌는 법정 요율이 들어가는
계산기는 제외 — 틀리면 리스크가 큼). 클라이언트 사이드 JS라 서버/API 불필요.
GEO(생성형 검색엔진 최적화)를 위해 각 계산기에 FAQPage 구조화 데이터를 붙인다.
쿠팡 상품과는 성격이 안 맞아 이 포스트들엔 쿠팡 섹션을 넣지 않는다.

목록이 유한하므로(현재 8개) 자취템의 매일-무한 상품리뷰 루프와는 별도로, 낮은 빈도(며칠에 1번)로
실행하는 걸 전제로 만들었다 — 이미 발행된 계산기는 제목으로 중복 판별해서 건너뛰고, 전부
발행되면 조용히 종료한다(다음 실행에서도 계속 "발행할 것 없음"으로 끝나되 에러는 아님)."""
import os
import re
import sys
import json
import datetime

import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

GOOGLE_OAUTH_TOKEN_STR = os.environ.get("SOLO_GOOGLE_TOKEN")
SOLO_BLOG_ID = os.environ.get("SOLO_BLOG_ID")
SCOPES = ["https://www.googleapis.com/auth/blogger"]

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")


def send_telegram(text):
    if not (TELEGRAM_TOKEN and CHAT_ID):
        print(text)
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": text}, timeout=15)
    except Exception as e:
        print(f"⚠️ 텔레그램 전송 실패: {e}")


def _get_blogger_service():
    token_info = json.loads(GOOGLE_OAUTH_TOKEN_STR)
    creds = Credentials.from_authorized_user_info(token_info, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("blogger", "v3", credentials=creds)


def get_recent_post_titles(blog_id, max_results=40):
    try:
        service = _get_blogger_service()
        posts = service.posts().list(blogId=blog_id, maxResults=max_results, fetchBodies=False).execute()
        return [p.get("title", "") for p in posts.get("items", [])]
    except Exception as e:
        print(f"⚠️ 최근 포스트 조회 실패: {e}")
        return []


def upload_to_blogger(title, content_html):
    service = _get_blogger_service()
    post = service.posts().insert(blogId=SOLO_BLOG_ID, body={"title": title, "content": content_html}).execute()
    return post.get("url")


# ==========================================
# 계산기 정의 — 전부 순수 수학/단위변환(세금·보험료 등 법정 요율 없음)
# ==========================================
CALCULATORS = [
    {
        "id": "pyeong_m2",
        "title": "평수 계산기 - 평 ↔ 제곱미터(㎡) 변환",
        "intro": "부동산 매물이나 원룸 안내문에 나오는 '평'과 실제 계약서/등기부에 쓰이는 '㎡(제곱미터)'는 "
                 "단위가 달라 헷갈리기 쉽습니다. 1평은 정확히 3.305785㎡로 환산됩니다.",
        "faq": [
            ("1평은 몇 제곱미터인가요?", "1평은 정확히 3.305785㎡입니다. 흔히 3.3㎡로 반올림해서 계산하기도 합니다."),
            ("전용면적 84㎡는 몇 평인가요?", "84 ÷ 3.305785 ≈ 25.4평입니다. 흔히 '국민평형'이라고 부르는 아파트 면적입니다."),
        ],
        "body": """
<div style="max-width:420px;margin:20px 0;padding:20px;border:1px solid #eee;border-radius:12px;">
  <label style="display:block;margin-bottom:6px;font-weight:600;">평(坪)</label>
  <input id="pyeong_input" type="number" step="0.01" placeholder="예: 25" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:16px;box-sizing:border-box;" oninput="pyeongToM2()">
  <div style="text-align:center;margin:10px 0;color:#999;">↕</div>
  <label style="display:block;margin-bottom:6px;font-weight:600;">제곱미터(㎡)</label>
  <input id="m2_input" type="number" step="0.01" placeholder="예: 82.6" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:16px;box-sizing:border-box;" oninput="m2ToPyeong()">
</div>
<script>
function pyeongToM2(){
  var v = parseFloat(document.getElementById('pyeong_input').value);
  document.getElementById('m2_input').value = isNaN(v) ? '' : (v * 3.305785).toFixed(2);
}
function m2ToPyeong(){
  var v = parseFloat(document.getElementById('m2_input').value);
  document.getElementById('pyeong_input').value = isNaN(v) ? '' : (v / 3.305785).toFixed(2);
}
</script>
""",
    },
    {
        "id": "inch_cm",
        "title": "인치 계산기 - 인치(inch) ↔ cm 변환",
        "intro": "모니터·TV 화면 크기는 인치로, 가구·자취방 실측은 cm로 표기되는 경우가 많아 자취방에 "
                 "가전을 들일 때 특히 자주 헷갈리는 단위입니다. 1인치는 정확히 2.54cm입니다.",
        "faq": [
            ("1인치는 몇 cm인가요?", "1인치는 정확히 2.54cm입니다."),
            ("27인치 모니터는 몇 cm인가요?", "27 × 2.54 ≈ 68.6cm입니다. 다만 이는 화면 대각선 길이 기준입니다."),
        ],
        "body": """
<div style="max-width:420px;margin:20px 0;padding:20px;border:1px solid #eee;border-radius:12px;">
  <label style="display:block;margin-bottom:6px;font-weight:600;">인치(inch)</label>
  <input id="inch_input" type="number" step="0.01" placeholder="예: 27" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:16px;box-sizing:border-box;" oninput="inchToCm()">
  <div style="text-align:center;margin:10px 0;color:#999;">↕</div>
  <label style="display:block;margin-bottom:6px;font-weight:600;">센티미터(cm)</label>
  <input id="cm_input" type="number" step="0.01" placeholder="예: 68.6" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:16px;box-sizing:border-box;" oninput="cmToInch()">
</div>
<script>
function inchToCm(){
  var v = parseFloat(document.getElementById('inch_input').value);
  document.getElementById('cm_input').value = isNaN(v) ? '' : (v * 2.54).toFixed(2);
}
function cmToInch(){
  var v = parseFloat(document.getElementById('cm_input').value);
  document.getElementById('inch_input').value = isNaN(v) ? '' : (v / 2.54).toFixed(2);
}
</script>
""",
    },
    {
        "id": "man_age",
        "title": "만 나이 계산기 - 생년월일로 바로 확인",
        "intro": "2023년 6월부터 법적 나이가 '만 나이'로 통일되면서, 세는나이와 헷갈리는 경우가 많습니다. "
                 "생년월일만 입력하면 오늘 기준 만 나이를 바로 계산해드립니다.",
        "faq": [
            ("만 나이는 어떻게 계산하나요?", "이번 해에서 태어난 해를 빼고, 아직 생일이 지나지 않았으면 1살을 뺍니다."),
            ("세는나이와 만 나이는 몇 살 차이나나요?", "생일이 지났으면 1살, 지나지 않았으면 2살 차이가 나는 경우가 일반적입니다."),
        ],
        "body": """
<div style="max-width:420px;margin:20px 0;padding:20px;border:1px solid #eee;border-radius:12px;">
  <label style="display:block;margin-bottom:6px;font-weight:600;">생년월일</label>
  <input id="birth_input" type="date" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:16px;box-sizing:border-box;" oninput="calcManAge()">
  <div id="man_age_result" style="margin-top:14px;font-size:1.3em;font-weight:700;color:#3182f6;"></div>
</div>
<script>
function calcManAge(){
  var b = document.getElementById('birth_input').value;
  if(!b){ document.getElementById('man_age_result').innerText=''; return; }
  var birth = new Date(b);
  var today = new Date();
  var age = today.getFullYear() - birth.getFullYear();
  var hadBirthday = (today.getMonth() > birth.getMonth()) ||
    (today.getMonth() === birth.getMonth() && today.getDate() >= birth.getDate());
  if(!hadBirthday) age -= 1;
  document.getElementById('man_age_result').innerText = '만 ' + age + '세';
}
</script>
""",
    },
    {
        "id": "dday",
        "title": "디데이(D-day) 계산기 - 특정 날짜까지 남은 일수",
        "intro": "시험일, 이사 예정일, 계약 만료일처럼 특정 날짜까지 며칠 남았는지(혹은 며칠 지났는지) "
                 "바로 확인할 수 있는 계산기입니다.",
        "faq": [
            ("D-day 계산은 당일을 포함하나요?", "이 계산기는 오늘과 목표일의 날짜 차이를 그대로 계산합니다(목표일 당일은 D-0)."),
            ("지난 날짜를 넣으면 어떻게 되나요?", "이미 지난 날짜라면 며칠이 지났는지(D+n) 표시됩니다."),
        ],
        "body": """
<div style="max-width:420px;margin:20px 0;padding:20px;border:1px solid #eee;border-radius:12px;">
  <label style="display:block;margin-bottom:6px;font-weight:600;">목표 날짜</label>
  <input id="dday_input" type="date" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:16px;box-sizing:border-box;" oninput="calcDday()">
  <div id="dday_result" style="margin-top:14px;font-size:1.3em;font-weight:700;color:#3182f6;"></div>
</div>
<script>
function calcDday(){
  var d = document.getElementById('dday_input').value;
  if(!d){ document.getElementById('dday_result').innerText=''; return; }
  var target = new Date(d + 'T00:00:00');
  var today = new Date();
  today = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  var diff = Math.round((target - today) / 86400000);
  document.getElementById('dday_result').innerText = diff === 0 ? 'D-DAY' : (diff > 0 ? ('D-' + diff) : ('D+' + Math.abs(diff)));
}
</script>
""",
    },
    {
        "id": "bmi",
        "title": "BMI 계산기 - 체질량지수로 확인하는 표준 체중",
        "intro": "키와 몸무게만 입력하면 체질량지수(BMI)를 바로 계산하고, 저체중/정상/과체중/비만 구간을 안내해드립니다.",
        "faq": [
            ("BMI는 어떻게 계산하나요?", "체중(kg)을 키(m)의 제곱으로 나눈 값입니다. 예: 70kg, 175cm → 70 ÷ 1.75² ≈ 22.9"),
            ("BMI 정상 범위는 얼마인가요?", "대한비만학회 기준 18.5~22.9가 정상 범위이며, 23 이상은 과체중, 25 이상은 비만으로 분류됩니다."),
        ],
        "body": """
<div style="max-width:420px;margin:20px 0;padding:20px;border:1px solid #eee;border-radius:12px;">
  <label style="display:block;margin-bottom:6px;font-weight:600;">키(cm)</label>
  <input id="bmi_height" type="number" step="0.1" placeholder="예: 175" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:16px;box-sizing:border-box;margin-bottom:10px;" oninput="calcBmi()">
  <label style="display:block;margin-bottom:6px;font-weight:600;">몸무게(kg)</label>
  <input id="bmi_weight" type="number" step="0.1" placeholder="예: 70" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:16px;box-sizing:border-box;" oninput="calcBmi()">
  <div id="bmi_result" style="margin-top:14px;font-size:1.3em;font-weight:700;color:#3182f6;"></div>
</div>
<script>
function calcBmi(){
  var h = parseFloat(document.getElementById('bmi_height').value) / 100;
  var w = parseFloat(document.getElementById('bmi_weight').value);
  var out = document.getElementById('bmi_result');
  if(!h || !w){ out.innerText=''; return; }
  var bmi = w / (h * h);
  var cat = bmi < 18.5 ? '저체중' : (bmi < 23 ? '정상' : (bmi < 25 ? '과체중' : '비만'));
  out.innerText = 'BMI ' + bmi.toFixed(1) + ' (' + cat + ')';
}
</script>
""",
    },
    {
        "id": "discount",
        "title": "할인율 계산기 - 할인가/할인율 바로 계산",
        "intro": "쇼핑할 때 정가와 할인가만 알면 할인율을, 정가와 할인율만 알면 실제 할인가를 바로 계산할 수 있습니다.",
        "faq": [
            ("할인율은 어떻게 계산하나요?", "(정가 - 할인가) ÷ 정가 × 100 으로 계산합니다."),
            ("정가 5만원에서 30% 할인받으면 얼마인가요?", "50,000 × (1 - 0.3) = 35,000원입니다."),
        ],
        "body": """
<div style="max-width:420px;margin:20px 0;padding:20px;border:1px solid #eee;border-radius:12px;">
  <label style="display:block;margin-bottom:6px;font-weight:600;">정가(원)</label>
  <input id="disc_price" type="number" placeholder="예: 50000" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:16px;box-sizing:border-box;margin-bottom:10px;" oninput="calcDiscount()">
  <label style="display:block;margin-bottom:6px;font-weight:600;">할인율(%)</label>
  <input id="disc_rate" type="number" placeholder="예: 30" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:16px;box-sizing:border-box;" oninput="calcDiscount()">
  <div id="disc_result" style="margin-top:14px;font-size:1.3em;font-weight:700;color:#3182f6;"></div>
</div>
<script>
function calcDiscount(){
  var p = parseFloat(document.getElementById('disc_price').value);
  var r = parseFloat(document.getElementById('disc_rate').value);
  var out = document.getElementById('disc_result');
  if(!p || isNaN(r)){ out.innerText=''; return; }
  var finalPrice = p * (1 - r / 100);
  out.innerText = '할인가: ' + Math.round(finalPrice).toLocaleString() + '원 (할인액 ' + Math.round(p - finalPrice).toLocaleString() + '원)';
}
</script>
""",
    },
    {
        "id": "weight_unit",
        "title": "무게 단위 변환기 - kg ↔ lb(파운드) 변환",
        "intro": "해외 직구 상품이나 운동기구 스펙은 파운드(lb) 단위로 표기된 경우가 많아, kg과 자주 헷갈립니다. 1kg은 약 2.20462lb입니다.",
        "faq": [
            ("1kg은 몇 파운드인가요?", "1kg은 약 2.20462lb입니다."),
            ("100lb는 몇 kg인가요?", "100 ÷ 2.20462 ≈ 45.36kg입니다."),
        ],
        "body": """
<div style="max-width:420px;margin:20px 0;padding:20px;border:1px solid #eee;border-radius:12px;">
  <label style="display:block;margin-bottom:6px;font-weight:600;">킬로그램(kg)</label>
  <input id="kg_input" type="number" step="0.01" placeholder="예: 70" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:16px;box-sizing:border-box;" oninput="kgToLb()">
  <div style="text-align:center;margin:10px 0;color:#999;">↕</div>
  <label style="display:block;margin-bottom:6px;font-weight:600;">파운드(lb)</label>
  <input id="lb_input" type="number" step="0.01" placeholder="예: 154.3" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:16px;box-sizing:border-box;" oninput="lbToKg()">
</div>
<script>
function kgToLb(){
  var v = parseFloat(document.getElementById('kg_input').value);
  document.getElementById('lb_input').value = isNaN(v) ? '' : (v * 2.20462).toFixed(2);
}
function lbToKg(){
  var v = parseFloat(document.getElementById('lb_input').value);
  document.getElementById('kg_input').value = isNaN(v) ? '' : (v / 2.20462).toFixed(2);
}
</script>
""",
    },
    {
        "id": "percent",
        "title": "퍼센트(%) 계산기 - A는 B의 몇 %인지 바로 계산",
        "intro": "'이 숫자가 전체의 몇 %인지', '전체의 몇 %가 얼마인지'를 바로 계산할 수 있는 퍼센트 계산기입니다.",
        "faq": [
            ("A는 B의 몇 %인지 어떻게 계산하나요?", "A ÷ B × 100 으로 계산합니다. 예: 30은 200의 15%입니다."),
            ("전체의 몇 %가 얼마인지는 어떻게 계산하나요?", "전체 × (퍼센트 ÷ 100)으로 계산합니다. 예: 200의 15%는 30입니다."),
        ],
        "body": """
<div style="max-width:420px;margin:20px 0;padding:20px;border:1px solid #eee;border-radius:12px;">
  <label style="display:block;margin-bottom:6px;font-weight:600;">A (부분값)</label>
  <input id="pct_a" type="number" placeholder="예: 30" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:16px;box-sizing:border-box;margin-bottom:10px;" oninput="calcPercent()">
  <label style="display:block;margin-bottom:6px;font-weight:600;">B (전체값)</label>
  <input id="pct_b" type="number" placeholder="예: 200" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:16px;box-sizing:border-box;" oninput="calcPercent()">
  <div id="pct_result" style="margin-top:14px;font-size:1.3em;font-weight:700;color:#3182f6;"></div>
</div>
<script>
function calcPercent(){
  var a = parseFloat(document.getElementById('pct_a').value);
  var b = parseFloat(document.getElementById('pct_b').value);
  var out = document.getElementById('pct_result');
  if(isNaN(a) || !b){ out.innerText=''; return; }
  out.innerText = 'A는 B의 ' + (a / b * 100).toFixed(2) + '%';
}
</script>
""",
    },
]


def build_faq_jsonld(faq_pairs):
    entities = [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
        for q, a in faq_pairs
    ]
    ld = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": entities}
    return f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>'


def build_calculator_html(calc):
    faq_html = "".join(
        f'<h3>Q. {q}</h3><p>A. {a}</p>' for q, a in calc["faq"]
    )
    return (
        f'<p>{calc["intro"]}</p>'
        f'{calc["body"]}'
        f'{faq_html}'
        f'{build_faq_jsonld(calc["faq"])}'
    )


def pick_next_calculator(recent_titles):
    for calc in CALCULATORS:
        if calc["title"] not in recent_titles:
            return calc
    return None


def main():
    print("1) 최근 포스트 조회 중(중복 계산기 스킵용)...")
    recent_titles = set(get_recent_post_titles(SOLO_BLOG_ID, max_results=40))

    calc = pick_next_calculator(recent_titles)
    if not calc:
        print("✅ 계산기 목록 전부 발행 완료 — 오늘은 건너뜁니다.")
        return

    print(f"2) 선택된 계산기: {calc['title']}")
    html_content = build_calculator_html(calc)
    print(f"3) HTML 조립 완료 (길이 {len(html_content)})")

    print("4) 블로거 발행 중...")
    try:
        link = upload_to_blogger(calc["title"], html_content)
        print(f"✅ 발행 완료: {link}")
        send_telegram(f"✅ [자취템/계산기] 자동 발행 완료!\n🧮 {calc['title']}\n👉 {link}")
    except Exception as e:
        print(f"❌ 발행 실패: {e}")
        send_telegram(f"❌ [자취템/계산기] 발행 실패: {e}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        raise
