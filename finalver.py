import folium
import json
import pandas as pd
import re
from branca.element import Element
from datetime import datetime, timezone, timedelta

import requests
import time
import asyncio
import aiohttp

#윈도우 꼬장 부릴거 같아서 이거는 추가함
import sys
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 1. 위장막 설정 (맨 위에 딱!)
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# 1. 전투 JSON은 헤더 없이도 잘 되지만, 넣어서 나쁠 건 없습니다.
url_battle = "https://www.erepublik.com/en/military/campaignsJson/list"
response_battle = requests.get(url_battle, headers=headers) # 위장막 장착!

# 1. 고정 데이터 로드
df_fixed = pd.read_csv('fixeddata.csv')
df_fixed['region id'] = df_fixed['region id'].astype(str)

# 2. JSON 다운로드
url = "https://www.erepublik.com/en/military/campaignsJson/list"

# 위장막(headers)을 여기서도 반드시 써주세요!
response = requests.get(url, headers=headers)

if response.status_code == 200:
    try:
        data = response.json()
        print("✅ 전투 JSON 확보 성공!")
    except requests.exceptions.JSONDecodeError:
        print("❌ 서버가 이상한 데이터를 보냈습니다. (JSON이 아님)")
        print(f"내용 일부: {response.text[:100]}") # 뭐가 왔는지 앞부분만 살짝 보기
        data = {"battles": {}, "countries": {}} # 빈 데이터로 초기화해서 뻑 방지
else:
    print(f"❌ 서버 접속 실패! 상태코드: {response.status_code}")
    data = {"battles": {}, "countries": {}}


# 3. 국가 ID → 이름 매핑 딕셔너리 생성
countries = data.get('countries', {})
country_map = {str(c['id']): c['name'] for c in countries.values()}

# 4. 전투 정보 파싱
battles = data.get('battles', {})
all_region_report = []

for battle_id, battle_info in battles.items():
    region_id = str(battle_info.get('region', {}).get('id', ''))
    
    # 공격자/방어자 ID → 이름 변환
    inv_id = str(battle_info.get('inv', {}).get('id', ''))
    def_id = str(battle_info.get('def', {}).get('id', ''))

    # 2. 🚩 포인트 확보 (사령관님 스타일로 딸깍!)
    inv_points = battle_info.get('inv', {}).get('points', 0)
    def_points = battle_info.get('def', {}).get('points', 0)

    # 🌟 전투 타입 추가!
    war_type = battle_info.get('war_type', 'unknown')  # 전투 종류
    
    invader = country_map.get(inv_id, 'Unknown')
    defender = country_map.get(def_id, 'Unknown')
    
    battle_url = f"https://www.erepublik.com/en/military/battlefield/{battle_id}"
    
    all_region_report.append({
        'region id': region_id,
        'current country': defender,
        'invader': invader,
        'battle url': battle_url,
        'invader points': inv_points,
        'defender points': def_points,
        'war_type': war_type  # 🌟 추가!  
    })

# 5. 데이터프레임 생성
df_live = pd.DataFrame(all_region_report)

# 6. 합체
df = pd.merge(df_fixed, df_live, on='region id', how='left')

# 7. 저장
df.to_csv('erepregiondata.csv', index=False, encoding='utf-8-sig')
print(f"으하하하! 총 {len(df)}개 지역 결합 완료!")
print(f"현재 전투 중인 지역: {len(df_live)}개")

# 8. 빈칸 정찰 작전 개시 (current country가 비어있는 지역만!)
df_target = df[df['current country'].isna()]
print(f"🕵️ 현재 평화로운 지역 {len(df_target)}곳을 정찰합니다...")





# A. 정찰병 한 명 한 명의 행동 요령 정의
async def fetch_city_data(session, index, city_id, region_id):
    url = f"https://www.erepublik.com/en/main/city-data/{city_id}/overview"
    try:
        # 비동기에서도 영자의 눈을 피하기 위한 미세한 간격
        await asyncio.sleep(0.3)
        
        async with session.get(url, headers=headers, timeout=10) as response:
            if response.status == 200:
                # 텍스트로 받아서 직접 json으로 변환 (보안상 더 안전)
                text = await response.text()
                import json
                data = json.loads(text)
                
                owner = data.get('cityInfo', {}).get('countryName', 'Unknown')
                print(f"✅ [Region {region_id}] 정찰 성공 -> {owner}")
                return index, owner
            else:
                print(f"❌ [Region {region_id}] 실패 (코드: {response.status})")
                return index, None
    except Exception as e:
        print(f"⚠️ [Region {region_id}] 교전 중 오류: {e}")
        return index, None

# B. 정찰대 전체를 지휘하는 지휘소
async def main_scout_operation(target_df):
    # 권장 사항: 지금처럼 잘 돌아간다면 그냥 쓰셔도 무방하지만, 
    # 만약 어느 날 갑자기 ❌ 실패 (코드: 403)나 429(Too Many Requests)가 뜨기 시작하면 
    # 그때 아래의 limit=10 장치를 장착하시면 됩니다.
    # # 한 번에 딱 10명만 동시 접속하도록 제한! (이게 진짜 안전장치) 
    connector = aiohttp.TCPConnector(limit=10)
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        for index, row in target_df.iterrows():
            # 타겟 하나하나를 임무(task)로 등록
            tasks.append(fetch_city_data(session, index, row['city id'], row['region id']))
        
        # 모든 임무를 동시에 실행하고 보고서 취합!
        return await asyncio.gather(*tasks)

# # C. 실제 작전 실행 (방아쇠 당기기)
# 주석: Jupyter(코랩) 환경과 일반 파이썬 환경의 차이를 고려한 실행법입니다. 코렙이라면 try-except 문 활성화
# # 1. 특수 부품 설치 (코랩에 없는 녀석만!) #코랩에서 인스톨
# # !pip install nest_asyncio
# try:
#     # 일반적인 .py 파일 실행 환경
#     loop = asyncio.get_event_loop()
#     results = loop.run_until_complete(main_scout_operation(df_target))
# except RuntimeError:
#     # 코랩이나 이미 루프가 돌아가는 환경 (위 방식이 안될 때 대비)
#     nest_asyncio.apply()
results = asyncio.run(main_scout_operation(df_target))

# 9. 취합된 보고서를 메인 시트(df)에 기입
for res in results:
    if res and res[1]: # 결과가 있고 주인이 확인된 경우만
        idx, owner = res
        df.at[idx, 'current country'] = owner

# 10. 최종 승전 보고서 저장
df.to_csv('erepregiondata.csv', index=False, encoding='utf-8-sig')
print(f"🎊 작전 종료! 574개 전 구역 점령 완료! 으하하하!")














# UTC 기준으로 2시간을 더합니다! (UTC+2)
# 만약 UTC-5를 원하시면 hours=-5 로 바꾸면 끝! 으흐흐
target_time = datetime.now(timezone.utc) + timedelta(hours=-8)
update_time = target_time.strftime('%Y-%m-%d %H:%M') + " (UTC-8)"

# 1. 데이터 로드
df = pd.read_csv('erepregiondata.csv', encoding='utf-8-sig')

# 사령관님의 컬러 보급품 맵핑 으흐흐
# color_raw = """Romania#498f9eBrazil#6a9e8aItaly#8da9c4France#a3c4bcGermany#bfd7edHungary#d0e1f9China#4d648dSpain#5d5b6aCanada#75808aUSA#59b0c3Mexico#407088Argentina#132743Venezuela#edc9afUnited Kingdom#8ab6d6Switzerland#d4e2d4Netherlands#f0ead6Belgium#dfcdc3Austria#91a3b0Czech Republic#b4c5e4Poland#fbfff1Slovakia#95adbeNorway#66828eSweden#445c67Finland#498f9eUkraine#7897abRussia#3a506bBulgaria#5bc0beTurkey#1c2541Greece#394a51Japan#7fa99bSouth Korea#f6f4e6India#fddb3aIndonesia#52575dAustralia#8d93abSouth Africa#d6e0f0Republic of Moldova#89a4c7Portugal#b2c9abIreland#92a8d1Denmark#f7cac9Iran#dec2cbPakistan#c5d5cbIsrael#9fa8a3Thailand#e3e2b4Slovenia#a2b9bcCroatia#b2ad7fChile#878f99Serbia#6b5b95Malaysia#feb236Philippines#d64161Singapore#ff7b25Bosnia and Herzegovina#d5e1dfEstonia#e3eaa7Latvia#b5e7a0Lithuania#86af49North Korea#404040Uruguay#005b96Paraguay#b3cde0Bolivia#6497b1Peru#008080Colombia#76b5c5North Macedonia#e2e2e2Montenegro#afabacRepublic of China (Taiwan)#96ceb4Cyprus#ffeeadBelarus#ff6f61New Zealand#6b5b95Saudi Arabia#88b04bEgypt#92a8d1United Arab Emirates#955251Albania#b565a7Georgia#009b77Armenia#dd4124Nigeria#45b8acCuba#efc050"""
# color_raw = """Romania#eddf9eBrazil#9cccb3Italy#d48a57France#cc73c8Germany#729c5bHungary#66bca7China#938c66Spain#69567bCanada#c693c6USA#9183ccMexico#9febc4Argentina#6b838eVenezuela#cc9bcbUnited Kingdom#726b8fSwitzerland#7e695aNetherlands#cc9b9aBelgium#9fae6eAustria#ae7f7fCzech Republic#796eaePoland#b86261Slovakia#4848f7Norway#c5eb51Sweden#ebbc51Finland#868f6aUkraine#5e7f8fRussia#ec9f9eBulgaria#8f6b8eTurkey#eb52b7Greece#539bebJapan#ae6e6eSouth Korea#accc9aIndia#ebbdebIndonesia#809eaeAustralia#90ae80South Africa#ae80acRepublic of Moldova#aea36dPortugal#d7e8a2Ireland#cdc183Denmark#8f6a6aIran#95673dPakistan#ece4bdIsrael#ae6dacThailand#54896eSlovenia#6a5284Croatia#a49bccChile#e2ecbdSerbia#eb5252Malaysia#b8eb9dPhilippines#763276Singapore#c453c9Bosnia and Herzegovina#6faf8dEstonia#bfdce4Latvia#ccb09bLithuania#c1cc9bNorth Korea#708f5eUruguay#ab9febParaguay#665e8fBolivia#5e8f75Peru#afa680Colombia#83b4cbNorth Macedonia#869d62Montenegro#cba945Republic of China (Taiwan)#c4b3deCyprus#7d53ceBelarus#cb6489New Zealand#d3d152Saudi Arabia#729672Egypt#a05560United Arab Emirates#c175a7Albania#bc6c6cGeorgia#76529eArmenia#779cbeNigeria#558a51Cuba#d44938"""
color_raw = """Romania#FFE97FBrazil#7ACCA2Italy#d75e08France#CB37C7Germany#367c11Hungary#20b08eChina#6c6023Spain#270746Canada#c06dc1USA#6752CCMexico#7FFFBEArgentina#295166Venezuela#CB7ACCUnited Kingdom#342966Switzerland#49270fNetherlands#CC7A7ABelgium#7E992EAustria#994C4CCzech Republic#402E99Poland#a71919Slovakia#2e2effNorway#bfff00Sweden#ffb000Finland#576629Ukraine#144B66Russia#FF7F7FBulgaria#662965Turkey#ff00aaGreece#0079ffJapan#992E2ESouth Korea#96CC7AIndia#FEB3FFIndonesia#4C7F99Australia#66994CSouth Africa#994C98Republic of Moldova#99872EPortugal#defa87Ireland#CCB852Denmark#662929Iran#8a5321Pakistan#FFF2B3Israel#992E98Thailand#015b2eSlovenia#280055Croatia#877ACCChile#64FFB3Serbia#ff0000Malaysia#AAFF7FPhilippines#651466Singapore#CC52CBBosnia and Herzegovina#2E9963Estonia#B3FFD8Latvia#CC9C7ALithuania#B8CC7ANorth Korea#306614Uruguay#957FFFParaguay#211466Bolivia#14663CPeru#998C4CColombia#52A3CCNorth Macedonia#577D2FMontenegro#C9A22CRepublic of China (Taiwan)#BEA2EBCyprus#4802CEBelarus#C91E5DNew Zealand#D6D400Saudi Arabia#347235Egypt#800517United Arab Emirates#B93B8FAlbania#B02B2CGeorgia#3B007FArmenia#3E7BB6Nigeria#055D00Cuba#D6301D"""
country_colors = dict(re.findall(r'([^#]+)(#[a-fA-F0-9]{6})', color_raw))

country_codes = {
    'Romania': 'ro', 'Brazil': 'br', 'Italy': 'it', 'France': 'fr',
    'Germany': 'de', 'Hungary': 'hu', 'China': 'cn', 'Spain': 'es',
    'Canada': 'ca', 'USA': 'us', 'Mexico': 'mx', 'Argentina': 'ar',
    'Venezuela': 've', 'United Kingdom': 'gb', 'Switzerland': 'ch',
    'Netherlands': 'nl', 'Belgium': 'be', 'Austria': 'at',
    'Czech Republic': 'cz', 'Poland': 'pl', 'Slovakia': 'sk',
    'Norway': 'no', 'Sweden': 'se', 'Finland': 'fi', 'Ukraine': 'ua',
    'Russia': 'ru', 'Bulgaria': 'bg', 'Turkey': 'tr', 'Greece': 'gr',
    'Japan': 'jp', 'South Korea': 'kr', 'India': 'in', 'Indonesia': 'id',
    'Australia': 'au', 'South Africa': 'za', 'Republic of Moldova': 'md',
    'Portugal': 'pt', 'Ireland': 'ie', 'Denmark': 'dk', 'Iran': 'ir',
    'Pakistan': 'pk', 'Israel': 'il', 'Thailand': 'th', 'Slovenia': 'si',
    'Croatia': 'hr', 'Chile': 'cl', 'Serbia': 'rs', 'Malaysia': 'my',
    'Philippines': 'ph', 'Singapore': 'sg', 'Bosnia and Herzegovina': 'ba',
    'Estonia': 'ee', 'Latvia': 'lv', 'Lithuania': 'lt', 'North Korea': 'kp',
    'Uruguay': 'uy', 'Paraguay': 'py', 'Bolivia': 'bo', 'Peru': 'pe',
    'Colombia': 'co', 'North Macedonia': 'mk', 'Montenegro': 'me',
    'Republic of China (Taiwan)': 'tw', 'Cyprus': 'cy', 'Belarus': 'by',
    'New Zealand': 'nz', 'Saudi Arabia': 'sa', 'Egypt': 'eg',
    'United Arab Emirates': 'ae', 'Albania': 'al', 'Georgia': 'ge',
    'Armenia': 'am', 'Nigeria': 'ng', 'Cuba': 'cu'
}


# 1. 맨 위에 자원 보너스 딕셔너리 추가
resource_bonus = {
    # Food 계열
    'Grain': {'type': 'food', 'bonus': 25},
    'Fish': {'type': 'food', 'bonus': 10},
    'Fruits': {'type': 'food', 'bonus': 15},
    'Cattle': {'type': 'food', 'bonus': 20},
    'Deer': {'type': 'food', 'bonus': 30},
    
    # Weapon 계열
    'Iron': {'type': 'weapon', 'bonus': 10},
    'Saltpeter': {'type': 'weapon', 'bonus': 25},
    'Aluminum': {'type': 'weapon', 'bonus': 15},
    'Oil': {'type': 'weapon', 'bonus': 20},
    'Rubber': {'type': 'weapon', 'bonus': 30},
    
    # House 계열
    'Sand': {'type': 'house', 'bonus': 10},
    'Clay': {'type': 'house', 'bonus': 20},
    'Wood': {'type': 'house', 'bonus': 15},
    'Limestone': {'type': 'house', 'bonus': 25},
    'Granite': {'type': 'house', 'bonus': 30},
    
    # Aircraft 계열
    'Neodymium': {'type': 'aircraft', 'bonus': 30},
    'Magnesium': {'type': 'aircraft', 'bonus': 10},
    'Cobalt': {'type': 'aircraft', 'bonus': 25},
    'Titanium': {'type': 'aircraft', 'bonus': 15},
    'Wolfram': {'type': 'aircraft', 'bonus': 20}
}


name_to_id = {str(row['region']).strip(): str(row['region id']) for _, row in df.iterrows()}
neighbor_id_map = {}
region_info = {}

for _, row in df.iterrows():
    curr_id = str(row['region id'])
    n_names = [n.strip() for n in str(row['neighbours']).split(',')]
    neighbor_id_map[curr_id] = [name_to_id[name] for name in n_names if name in name_to_id]
    
    # 박스 정보에 'original' 추가 으흐흐
    region_info[curr_id] = {
        'region': str(row['region']),
        'city': str(row['city']),
        'owner': str(row.get('current country', 'Unknown')),
        'original': str(row.get('original country', 'Unknown'))
    }

# # 2. 지도 생성
# m = folium.Map(
#     location=[45.0, 25.0],
#     zoom_start=4,
#     tiles='https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png',
#     attr='&copy; CARTO'
# )

# 1. 지도를 만들 때 tiles=None으로 설정 (배경을 일단 비움)
m = folium.Map(
    location=[35.0, 125.0], #위도, 경도
    zoom_start=5,
    tiles=None  # <- 여기를 None으로!
)

# 2. 배경 레이어를 별도로 추가 (control=False로 메뉴에서 숨김)
folium.TileLayer(
    tiles='https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png',
    attr='&copy; CARTO',
    name='CartoDB Light', # 사실 숨길 거라 이름은 아무거나 해도 됩니다.
    control=False         # <- 이 녀석이 범인 검거의 핵심! (메뉴에 안 뜸)
).add_to(m)



# 3. 하단 정보 박스 (HTML/CSS) - REGION, OWNER, ORIGINAL 순서 으흐흐
info_box_html = """
<div id="info-box" style="
    position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%);
    width: 400px; z-index: 9999; background: rgba(255, 255, 255, 0.9);
    border: 3px solid #59b0c3; border-radius: 15px; padding: 15px;
    font-family: 'Arial', sans-serif; box-shadow: 0 -4px 20px rgba(0,0,0,0.3);
    pointer-events: none; text-align: center;
">
<div id="info-content">
        <div style="font-size: 12x; color: #7f8c8d; margin-bottom: 3px;">
            🕒 LAST UPDATE: {time_val}
        </div>
        <b style="font-size: 18px; color: #888;">지역 위에 마우스를 올리십시오.</b>
    </div>
</div>
""".replace("{time_val}", update_time) # 👈 중괄호 충돌 피하기 위한 필살기! 으흐흐
m.get_root().html.add_child(Element(info_box_html))

# info_box_html 아래에 추가 우측 박스
# info_box_html 아래에 추가
ranking_box_html = """
<style>
    #ranking-toggle {
        position: absolute;
        top: 80px;
        right: 10px;
        background: rgba(255, 255, 255, 0.95);
        border: 2px solid #59b0c3;
        border-radius: 10px;
        font-family: 'Arial', sans-serif;
        box-shadow: 0 2px 10px rgba(0,0,0,0.3);
        z-index: 1000;
        width: 50px;
        overflow: hidden;
        transition: width 0.4s ease;
    }
    
    #ranking-toggle.expanded {
        width: 250px;
    }
    
    #ranking-header {
        padding: 12px;
        cursor: pointer;
        font-weight: bold;
        text-align: center;
        color: #333;
        font-size: 14px;
        user-select: none;
        background: linear-gradient(to bottom, #f5f5f5, #e0e0e0);
        border-radius: 8px;
        white-space: nowrap;
    }
    
    #ranking-header:hover {
        background: linear-gradient(to bottom, #e0e0e0, #d0d0d0);
    }
    
    #ranking-content {
        max-height: 0;
        overflow: hidden;
        transition: max-height 0.3s ease;
        padding: 0 12px;
    }
    
    #ranking-content.expanded {
        max-height: 400px;
        overflow-y: auto;
        padding: 12px;
    }
    
    .tab-buttons {
        display: flex;
        gap: 5px;
        margin-bottom: 10px;
        opacity: 0;
        transition: opacity 0.3s ease 0.2s;
    }
    
    #ranking-toggle.expanded .tab-buttons {
        opacity: 1;
    }
    
    .tab-btn {
        flex: 1;
        padding: 6px 3px;
        border: none;
        background: #e0e0e0;
        cursor: pointer;
        border-radius: 5px;
        font-size: 11px;
        font-weight: bold;
        transition: all 0.3s;
    }
    
    .tab-btn:hover {
        background: #d0d0d0;
    }
    
    .tab-btn.active {
        background: #59b0c3;
        color: white;
    }
    
    .ranking-list {
        list-style: none;
        padding: 0;
        margin: 0;
    }
    
    .ranking-item {
        padding: 5px 8px;
        margin: 2px 0;
        background: #f9f9f9;
        border-radius: 5px;
        font-size: 12px;
        border-left: 3px solid #59b0c3;
        cursor: pointer;
    }
    
    .ranking-item:hover {
        background: #e8f4f8;
        border-left-color: #FF4500;
    }
    
    .rank-number {
        font-weight: bold;
        color: #666;
        margin-right: 5px;
    }
    
    .bonus-value {
        float: right;
        color: #27AE60;
        font-weight: bold;
        font-size: 11px;
    }
    
    #ranking-header-icon {
        display: inline;
    }
    
    #ranking-header-text {
        display: none;
    }
    
    #ranking-toggle.expanded #ranking-header-icon {
        display: none;
    }
    
    #ranking-toggle.expanded #ranking-header-text {
        display: inline;
    }
</style>

<div id="ranking-toggle">
    <div id="ranking-header" onclick="toggleRankingBox()">
        <span id="ranking-header-icon">🏆</span>
        <span id="ranking-header-text">🏆 RANKINGS ▼</span>
    </div>
    <div id="ranking-content">
        <div class="tab-buttons">
            <button class="tab-btn active" onclick="showRankingTab('food'); event.stopPropagation();">🍖</button>
            <button class="tab-btn" onclick="showRankingTab('weapon'); event.stopPropagation();">⚔️</button>
            <button class="tab-btn" onclick="showRankingTab('house'); event.stopPropagation();">🏠</button>
            <button class="tab-btn" onclick="showRankingTab('aircraft'); event.stopPropagation();">✈️</button>
        </div>
        <ul id="ranking-list" class="ranking-list"></ul>
    </div>
</div>
"""

m.get_root().html.add_child(Element(ranking_box_html))


# 4. 자바스크립트 (인접지역 ID 맵핑 + 정보창 업데이트)
custom_js = f"""
    var neighborMap = {json.dumps(neighbor_id_map)};
    var regionInfo = {json.dumps(region_info)};
    var countryColors = {json.dumps(country_colors)};
    var resourceBonus = {json.dumps(resource_bonus)};
    var countryCodes = {json.dumps(country_codes)};   // 🚩 추가!
    var allLayers = {{}};
    var resourceLayers = {{}};

    // 🚩 국기 이미지 HTML 생성 함수
    function getFlagImg(country) {{
        var code = countryCodes[country];
        if (code) {{
            return '<img src="https://flagcdn.com/16x12/' + code + '.png" style="margin-right: 4px; vertical-align: middle;">';
        }}
        return '';
    }}

    function forceResetAll() {{
        Object.keys(allLayers).forEach(function(id) {{
            var l = allLayers[id];
            var country = regionInfo[id] ? regionInfo[id].owner : "Unknown";
            var baseColor = countryColors[country] || "#59b0c3";
            if (l) {{
                l.setStyle({{ fillColor: baseColor, color: 'white', weight: 1, fillOpacity: 0.6, dashArray: '' }});
            }}
        }});
    }}

    
    function updateInfoBox(rid) {{
        var info = regionInfo[rid];
        var contentDiv = document.getElementById('info-content');
        if (info) {{
            var ownerFlag = getFlagImg(info.owner);
            var originalFlag = getFlagImg(info.original);
            
            contentDiv.innerHTML = `
                <div style="color: #000; line-height: 1.4; text-align: center;">
                    <div style="font-size: 18px; margin-bottom: 5px;"><b>${{info.region}}</b></div>
                    <div style="font-size: 16px;">current country : ${{ownerFlag}}<span style="color: #C0392B; font-weight: bold;">${{info.owner}}</span></div>
                    <div style="font-size: 16px; margin-bottom: 5px;">original country: ${{originalFlag}}<span style="color: #2E5A88; font-weight: bold;">${{info.original}}</span></div>
                    <div style="font-size: 14px; color: #666; border-top: 1px solid #ddd; padding-top: 3px;">CITY : ${{info.city}}</div>
                </div>`;
        }}
}}

    // 🌟 자원 보너스 계산 함수
    function calculateBonuses(resourcesText) {{
        if (!resourcesText || resourcesText === 'No resources') return null;
        
        var resources = resourcesText.split(',').map(r => r.trim());
        var bonuses = {{}};
        var resourceList = [];
        
        resources.forEach(function(res) {{
            if (resourceBonus[res]) {{
                var type = resourceBonus[res].type;
                var bonus = resourceBonus[res].bonus;
                
                if (!bonuses[type]) {{
                    bonuses[type] = 0;
                }}
                bonuses[type] += bonus;
                resourceList.push(res);
            }}
        }});
        
        return {{ bonuses: bonuses, resources: resourceList }};
    }}
    

    // 🌟 수정된 자원 정보 표시 함수
    function updateInfoBoxResource(rid, resources) {{
        var info = regionInfo[rid];
        var contentDiv = document.getElementById('info-content');
        if (info) {{
            var calculated = calculateBonuses(resources);
            
            var bonusHTML = '';
            if (calculated && Object.keys(calculated.bonuses).length > 0) {{
                bonusHTML = '<div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid #ddd;">';
                
                // 산업별 보너스 표시
                var bonusOrder = ['food', 'weapon', 'house', 'aircraft'];
                var bonusIcons = {{
                    'food': '🍖',
                    'weapon': '⚔️',
                    'house': '🏠',
                    'aircraft': '✈️'
                }};
                
                bonusOrder.forEach(function(type) {{
                    if (calculated.bonuses[type]) {{
                        bonusHTML += `
                            <div style="font-size: 15px; margin: 3px 0; font-weight: bold;">
                                ${{bonusIcons[type]}} ${{type.toUpperCase()}} +${{calculated.bonuses[type]}}%
                            </div>`;
                    }}
                }});
                bonusHTML += '</div>';
                
            // 🌟 자원 목록을 2x2 그리드로 배치!
            var detailedResources = calculated.resources.map(function(res) {{
                if (resourceBonus[res]) {{
                    var type = resourceBonus[res].type;
                    var bonus = resourceBonus[res].bonus;
                    return res + ': ' + type + ' ' + bonus + '%';
                }}
                return res;
            }});
            
            // 두 줄로 나누기
            var halfPoint = Math.ceil(detailedResources.length / 2);
            var firstRow = detailedResources.slice(0, halfPoint).join(', ');
            var secondRow = detailedResources.slice(halfPoint).join(', ');
            
            var resourceListHTML = '<div style="font-size: 13px; color: #7F8C8D; margin-top: 5px; font-weight: bold; line-height: 1.6;">' + 
                firstRow + '<br>' + secondRow + '</div>';
        }} else {{
            bonusHTML = '<div style="font-size: 14px; color: #95A5A6; margin-top: 5px;">No resources</div>';
            var resourceListHTML = '';
        }}
            
            contentDiv.innerHTML = `
                <div style="color: #000; line-height: 1.4; text-align: center;">
                    <div style="font-size: 18px; margin-bottom: 5px;"><b>${{info.region}}</b></div>
                    <div style="font-size: 16px; color: #D35400; font-weight: bold; margin: 8px 0;">
                        💎 RESOURCE BONUSES
                    </div>
                    ${{bonusHTML}}
                    ${{resourceListHTML}}
                    <div style="font-size: 14px; color: #666; border-top: 1px solid #ddd; padding-top: 3px; margin-top: 5px;">
                        CITY : ${{info.city}}
                    </div>
                </div>`;
        }}
    }}

    function highlightNeighbors(e) {{
        forceResetAll();
        var layer = e.target;
        var rid = layer.feature.properties['region id'].toString();
        updateInfoBox(rid);
        layer.setStyle({{ weight: 5, color: '#FF4500', fillOpacity: 0.8 }});
        var neighbors = neighborMap[rid] || [];
        neighbors.forEach(function(nId) {{
            if (allLayers[nId]) {{
                allLayers[nId].setStyle({{ weight: 4, color: '#00CED1', dashArray: '5, 5', fillOpacity: 0.4 }});
            }}
        }});
    }}

    function highlightResource(e) {{
        var layer = e.target;
        var rid = layer.feature.properties['region id'].toString();
        var resources = layer.feature.properties.resources || 'No resources';
        updateInfoBoxResource(rid, resources);
        layer.setStyle({{ weight: 3, color: '#FF6B35', fillOpacity: 0.9 }});
    }}

    function resetHighlight(e) {{
        forceResetAll();
        // 따옴표(') 대신 백틱(`)을 사용해서 여러 줄을 감싸줍니다!
        document.getElementById('info-content').innerHTML = `
            <div style="font-size: 12x; color: #7f8c8d; margin-bottom: 3px;">🕒 LAST UPDATE: {update_time}</div>
            <b style="font-size: 18px; color: #888;">지역 위에 마우스를 올리십시오.</b>
        `;
    }}

    // 🌟 새로 추가! 자원 레이어용 리셋 함수
    function resetResourceHighlight(e) {{
        var layer = e.target;
        var rid = layer.feature.properties['region id'].toString();
        if (resourceLayers[rid]) {{
            var originalStyle = resourceLayers[rid].originalStyle;
            layer.setStyle(originalStyle);
        }}
        document.getElementById('info-content').innerHTML = '<b style="font-size: 18px; color: #888;">지역 위에 마우스를 올리십시오.</b>';
    }}

    // 🏆 랭킹 관련 변수
    var allRankings = {{}};
    var isBoxExpanded = false;
    var isContentExpanded = false;
    
    // 🏆 랭킹 계산
    function calculateRankings() {{
        var rankings = {{ food: [], weapon: [], house: [], aircraft: [] }};
        
        var regionResources = {json.dumps({
            str(row['region id']): {
                'resources': [r.strip() for r in str(row.get('resources', '')).split(',') if r.strip() and r.strip().lower() != 'nan'],
                'lat': float(row['lat']) if pd.notna(row['lat']) else None,
                'lon': float(row['lon']) if pd.notna(row['lon']) else None
            }
            for _, row in df.iterrows()
        })};
        
        Object.keys(regionInfo).forEach(function(rid) {{
            var info = regionInfo[rid];
            var resData = regionResources[rid];
            if (!resData) return;
            
            var resources = resData.resources || [];
            var bonuses = {{}};
            
            resources.forEach(function(res) {{
                if (resourceBonus[res]) {{
                    var type = resourceBonus[res].type;
                    var bonus = resourceBonus[res].bonus;
                    if (!bonuses[type]) bonuses[type] = 0;
                    bonuses[type] += bonus;
                }}
            }});
            
            Object.keys(bonuses).forEach(function(type) {{
                rankings[type].push({{ 
                    region: info.region, 
                    bonus: bonuses[type], 
                    rid: rid,
                    lat: resData.lat,
                    lon: resData.lon
                }});
            }});
        }});
        
        Object.keys(rankings).forEach(function(type) {{
            rankings[type].sort(function(a, b) {{ return b.bonus - a.bonus; }});
            rankings[type] = rankings[type].slice(0, 20);
        }});
        
        return rankings;
    }}
    
        // 🏆 박스 토글 (수정 버전)
        function toggleRankingBox() {{
            var box = document.getElementById('ranking-toggle');
            var content = document.getElementById('ranking-content');
            var headerText = document.getElementById('ranking-header-text');
            
            if (!isBoxExpanded) {{
                // 1단계: 박스 가로 확장
                box.classList.add('expanded');
                isBoxExpanded = true;
            }} else if (!isContentExpanded) {{
                // 2단계: 내용 세로 펼침
                content.classList.add('expanded');
                headerText.innerHTML = 'RESOURCE RANKING ▲';
                isContentExpanded = true;
            }} else {{
                // 3단계: 다시 접기 (역순으로)
                content.classList.remove('expanded');
                headerText.innerHTML = 'RESOURCE RANKING ▼';
                isContentExpanded = false;
                
                // 잠시 후 박스도 접기
                setTimeout(function() {{
                    box.classList.remove('expanded');
                    isBoxExpanded = false;
                }}, 300);  // 애니메이션 시간과 맞춤
    }}
}}
    
    // 🏆 탭 전환
    function showRankingTab(type) {{
        document.querySelectorAll('.tab-btn').forEach(function(btn) {{
            btn.classList.remove('active');
        }});
        event.target.classList.add('active');
        
        var listEl = document.getElementById('ranking-list');
        var rankings = allRankings[type] || [];
        
        if (rankings.length === 0) {{
            listEl.innerHTML = '<li class="ranking-item">No regions</li>';
            return;
        }}
        
        var html = '';
        rankings.forEach(function(item, index) {{
            html += '<li class="ranking-item" onclick="flyToRegion(' + 
                item.lat + ',' + item.lon + ')">' +
                '<span class="rank-number">' + (index + 1) + '.</span>' +
                item.region +
                '<span class="bonus-value">+' + item.bonus + '%</span>' +
                '</li>';
        }});
        
        listEl.innerHTML = html;
    }}
    
    // 🏆 지역으로 이동
    function flyToRegion(lat, lon) {{
        if (!lat || !lon) return;
        
        var mapElement = document.querySelector('.leaflet-container');
        if (mapElement && mapElement._leaflet_id) {{
            for (var key in window) {{
                if (window[key] && window[key]._container === mapElement) {{
                    window[key].flyTo([lat, lon], 8, {{ duration: 1.5 }});
                    break;
                }}
            }}
        }}
    }}

    
    // 🏆 초기화
    window.addEventListener('load', function() {{
        allRankings = calculateRankings();
        showRankingTab('food');
    }});
"""

m.get_root().header.add_child(Element(f"<script>{custom_js}</script>"))

# 5. GeoJson 로드 및 메인 도색 레이어
with open('erepmap.geojson', encoding='utf-8') as f:
    gj_data = json.load(f)

def main_style(feature):
    rid = str(feature['properties']['region id'])
    country = region_info.get(rid, {}).get('owner', 'Unknown')
    return {
        'fillColor': country_colors.get(country, "#59b0c3"),
        'color': 'white',
        'weight': 1,
        'fillOpacity': 0.6
    }

js_callback = folium.JsCode("""
function(feature, layer) {
    var rid = feature.properties['region id'].toString();
    allLayers[rid] = layer;
    layer.on({ mouseover: highlightNeighbors, mouseout: resetHighlight });
}
""")


folium.GeoJson(
    gj_data,
    name="Political Map (Countries)",
    style_function=main_style,
    on_each_feature=js_callback
).add_to(m)

# --- 전장 전용 레이어 (공방 정보 추가 버전) ---
battle_layer = folium.FeatureGroup(name="⚔️ Battlefields")

for _, row in df.iterrows():
    if pd.notna(row['lat']) and pd.notna(row['lon']):
        b_url = str(row.get('battle url', '')).strip()
        
        if b_url.startswith('http'):
            # 데이터 추출 (공격자와 방어자)
            attacker = str(row.get('invader', 'Unknown'))
            defender = str(row.get('current country', 'Unknown'))
            attacker_point = str(int(float(row.get('invader points', 0))))
            defender_point = str(int(float(row.get('defender points', 0))))
            # 🌟 새 방식 (간단!)
            war_type = str(row.get('war_type', 'unknown'))
            
            
            # 🌟 아이콘 선택
            if war_type == 'resistance':
                icon_color = "#2980b9"
                icon_emoji = "🔥"
                battle_type = "RESISTANCE WAR"

            elif war_type == 'civil':  # 또는 다른 값
                icon_emoji = "🚩"
                battle_type = "CIVIL WAR"

            elif war_type == 'dictatorship':
                icon_emoji = "👑"
                battle_type = "DICTATORSHIP WAR"

            elif war_type == 'airstrike' :
                icon_emoji =  "✈️"
                battle_type = 'Airstrike'

            else:
                icon_color = "#FF4500"
                icon_emoji = "⚔️"
                battle_type = "BATTLE"
                
#  # 저항전 대안 아이콘:
# "🛡️"  # 방패 (현재)
# "✊"   # 주먹 (저항)
# "🔥"  # 불 (봉기)
# "⚡"  # 번개 (반란)
# "🚩"  # 깃발 (해방)


            # 🚩 국기 이미지 URL 생성
            attacker_code = country_codes.get(attacker, 'un')  # 없으면 UN 깃발
            defender_code = country_codes.get(defender, 'un')
            attacker_flag = f'<img src="https://flagcdn.com/16x12/{attacker_code}.png" style="margin-right: 4px; vertical-align: middle;">'
            defender_flag = f'<img src="https://flagcdn.com/16x12/{defender_code}.png" style="margin-right: 4px; vertical-align: middle;">'
            
            # 1. 저항전이면 빨간색 "RESISTANCE" 딱지를 준비합니다.
            res_label = ""
            if war_type == 'resistance':
                res_label = '<div style="color: #e67e22; font-weight: bold; font-size: 15px; margin-top: -5px;">🔥 RESISTANCE WAR</div>'             
            elif war_type == 'civil':  # 또는 다른 값
                res_label = '<div style="color: #e67e22; font-weight: bold; font-size: 15px; margin-top: -5px;"> 🚩 Civil War </div>'      
            elif war_type == 'dictatorship':
                res_label = '<div style="color: #e67e22; font-weight: bold; font-size: 15px; margin-top: -5px;"> 👑 Dictatorship </div>'
            elif war_type == 'airstrike' :
                res_label = '<div style="color: #e67e22; font-weight: bold; font-size: 15px; margin-top: -5px;"> ✈️ Airstrike </div>'

            # 팝업을 '전술 보고서' 느낌으로 재구성 으흐흐
            popup_html = f"""
            <div style="width: 220px; font-family: 'Arial'; border: 2px solid {icon_color}; padding: 10px; border-radius: 8px; background: #fff;">
                <div style="text-align: center; font-weight: bold; font-size: 16px; margin-bottom: 5px; color: #333;">
                    {row['region']} FRONT
                </div>

                <div style="text-align: center; margin-bottom: 5px;">
                    {res_label}  </div>    

                <div style="font-size: 17px; line-height: 1.6; border-top: 1px solid #ddd; padding-top: 5px;">
                    <span style="color: #e74c3c; font-weight: bold;">[ATTACKER]</span><br> 
                    {attacker_flag} {attacker} {attacker_point} <br>
                    <span style="color: #2980b9; font-weight: bold;">[DEFENDER]</span><br> 
                    {defender_flag} {defender} {defender_point}
                </div>
                <div style="margin-top: 10px; text-align: center;">
                    <a href="{b_url}" target="_blank" 
                    style="display: block; padding: 10px; background: #FF4500; color: #fff; 
                            text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 13px;">
                        ⚔️ JOIN THE BATTLE
                    </a>
                </div>
            </div>
            """
            
            icon_style = f"""<div style="font-size: 20px; text-shadow: 1px 1px 3px #000; cursor: pointer;">{icon_emoji}</div>"""
            
            folium.Marker(
                location=[row['lat'], row['lon']],
                icon=folium.DivIcon(html=icon_style),
                popup=folium.Popup(popup_html, max_width=220),
                z_index=1000
            ).add_to(battle_layer)

battle_layer.add_to(m)

# --- 자원 매장지 전용 레이어 (음영 버전) ---
resource_layer = folium.FeatureGroup(name="💎 Resource Deposits", show=False) # 기본은 꺼둠(딸깍용)

# 🌟 자원 정보를 properties에 추가!
for feature in gj_data['features']:
    rid = str(feature['properties']['region id'])
    res_row = df[df['region id'].astype(str) == rid]['resources']
    if not res_row.empty and pd.notna(res_row.values[0]):
        feature['properties']['resources'] = str(res_row.values[0])
    else:
        feature['properties']['resources'] = ''


def get_res_style(feature):
    rid = str(feature['properties']['region id'])
    # 해당 지역의 자원 데이터 추출
    res_row = df[df['region id'].astype(str) == rid]['resources']
    
    # 자원 개수 파악 으흐흐
    if not res_row.empty and pd.notna(res_row.values[0]):
        res_list = [r.strip() for r in str(res_row.values[0]).split(',') if r.strip()]
        count = len(res_list)
    else:
        count = 0

    # 개수에 따른 음영 (너무 튀지 않는 SteelBlue 계열)
    if count == 0:
        fill_opacity = 0
        fill_color = 'transparent'
    elif count == 1:
        fill_opacity = 0.3
        fill_color = '#4682B4' # SteelBlue
    elif count == 2:
        fill_opacity = 0.5
        fill_color = '#4682B4'
    else:
        fill_opacity = 0.7  # 3개 이상은 진하게!
        fill_color = '#2E5A88' # 더 깊은 블루

    return {
        'fillColor': fill_color,
        'color': 'white' if count > 0 else 'transparent', # 자원 있는 곳만 테두리
        'weight': 1,
        'fillOpacity': fill_opacity,
        'interactive': True # 마우스 이벤트는 메인 레이어에 양보! 으흐흐
    }

# 🌟 자원 레이어용 콜백 추가!
resource_callback = folium.JsCode("""
function(feature, layer) {
    var rid = feature.properties['region id'].toString();
    var resources = feature.properties.resources || '';
    
    // 자원이 있는 지역만 이벤트 활성화
    if (resources) {
        // 원본 스타일 저장
        var style = layer.options;
        resourceLayers[rid] = {
            layer: layer,
            originalStyle: {
                fillColor: style.fillColor,
                color: style.color,
                weight: style.weight,
                fillOpacity: style.fillOpacity
            }
        };
        layer.on({ 
            mouseover: highlightResource, 
            mouseout: resetResourceHighlight 
        });
    }
}
""")


folium.GeoJson(
    gj_data,
    style_function=get_res_style,
    smooth_factor=0.5,
    on_each_feature=resource_callback  # 🌟 콜백 추가!
).add_to(resource_layer)


# --- 2. 여기에 바로 복붙! (글자 부대 투입) 으흐흐 ---
# 2. 자원 있는 곳에만 '클릭용 아이콘' 배치
for _, row in df.iterrows():
    res_raw = str(row.get('resources', '')).strip()
    # 좌표 없거나 자원 없으면 패스! 으흐흐
    if pd.isna(row['lat']) or pd.isna(row['lon']) or not res_raw or res_raw.lower() == 'nan':
        continue

   
    # 큼직한 글자 디자인 (가독성 보급형)
    label_html = f"""
        <div style="pointer-events: none; width: 250px;">
            <div style="
                font-size: 12px; /* 큼직하게! */
                font-weight: 900; 
                color: #121010; /* 눈에 띄는 오렌지색 */
                text-shadow: 2px 2px 3px white, -2px -2px 3px white; /* 글자 테두리 효과 */
                line-height: 1.1;
                margin-left: 8px;
            ">
                {res_raw}<br>
                <span style="font-size: 12px; color: #2980B9;"></span>
            </div>
        </div>
    """
    
    # 1. 아이콘은 아주 작은 '점'으로 (위치 확인용)
    folium.CircleMarker(
        location=[row['lat'], row['lon']],
        radius=2, # 더 작게! 으흐흐
        color='#D35400',
        fill=True,
        fill_opacity=1
    ).add_to(resource_layer)

    # # 2. 그 옆에 큼직한 텍스트 박제
    # folium.Marker(
    #     location=[row['lat'], row['lon']],
    #     icon=folium.DivIcon(
    #         icon_anchor=(0, 20), # 점 바로 옆에 글자가 오도록 조정
    #         html=label_html
    #     )
    # ).add_to(resource_layer)

resource_layer.add_to(m)

# # 6번 섹션(도시 마커)은 아주 작은 점으로만 남겨서 평소엔 안 보이게 하거나 시각적 보조만 합니다.
# for _, row in df.iterrows():
#     if pd.notna(row['lat']) and pd.notna(row['lon']):
#         # 평상시 도시는 아주 작고 투명한 점으로 (전술적 방해 최소화)
#         folium.CircleMarker(
#             location=[row['lat'], row['lon']],
#             radius=4, color='white', weight=1, fill=True,
#             fill_color="#5D8FA3", fill_opacity=0.4
#         ).add_to(m)

folium.LayerControl(collapsed=False).add_to(m)
m.save('index.html')
print("으흐흐흐... 사령관님! 모든 전술적 요소가 통합된 최종 지도가 완성되었습니다!")