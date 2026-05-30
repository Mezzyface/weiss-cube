"""
Crawls heartofthecards.com translation pages for all sets not yet saved locally.

Strategy:
  1. For sets in sets_manifest.json with a candidate_url/translation_url → fetch that directly.
  2. For sets on the site but NOT in the manifest → hit the cardlist page to discover the link.

Saves HTML to data/html/<set_id>.html. Skips if file already exists.
Polite: 1.5s between requests, retries once on failure.
"""

import json
import os
import re
import time
import sys

import requests
from bs4 import BeautifulSoup

BASE = "https://www.heartofthecards.com"
REPO = os.path.dirname(os.path.abspath(__file__))
HTML_DIR = os.path.join(REPO, "data", "html")
MANIFEST_PATH = os.path.join(REPO, "data", "sets_manifest.json")

DELAY = 1.5  # seconds between requests

# All set IDs found on the site (from cardlist page)
SITE_SETS = [
    "S18-ws2012std", "W108-wsrawagaetd", "W11-ws2010wtd", "W31-ws2014wtd",
    "W127-wsrawaogiritd", "S103-wsrawaritd", "S76-wsrawallrtd", "S76-wsrawalbtdp",
    "S35-ws2015std", "W110-wsrawayatd", "S102-wsazurtd", "S15-ws2011std",
    "W125-rawmujicatd", "W54-wsrawbdagtdp", "W54-wsrawbdhhwtdp", "W54-wsrawbdpmrawtd",
    "W54-wsrawbdpptdp", "W54-wsrawbdgbppptdp", "W54-wsrawbdrstdp", "W135-wsrawmugentd",
    "WE42-wsrawbdmgtd", "W73-wsrawrastdp", "W47-ws2017wtd", "W112-wsrawbarchtd",
    "W107-wsrawbtrtd", "S78-wsrawbfrtd", "W66-wsrawccstdp", "S48-wschaincctd",
    "S96-wsrawchainsawtd", "W40-ws2015wtd", "S114-wsrawcscmvtd", "S28-ws2014std",
    "S97-wsrawd4djhalltd", "S86-wsdciderawtd", "W23-ws2013wtd", "W18-ws2012wtd",
    "W09-ws2010wtd", "W01-ws2008wtd", "S118-wsrawdddtd", "S57-wsrawfranxxtdp",
    "W79-wsrawdaltdp", "W29-ws2013wtd", "WS02-wsrawdengekiwtd", "S02-ws2008std",
    "S12-ws2010std", "S09-ws2010std", "S53-wsrawfapotdp", "S75-wsrawfgobtdp",
    "S17-ws2012std", "S03-ws2008std", "S34-ws2015std", "S108-wsrawfrierentd",
    "W65-wsrawfantasiatdp", "W120-wsrawfujimi2td", "W124-wsrawgakumastd", "S23-ws2013std",
    "W33-ws2014wtd", "SE48-rawgbcrytd", "S63-wsrawgoblintdp", "S54-wsrawgztdp",
    "S16-ws2011std", "S52-wsttglrawtd", "W08-ws2009wtd", "S22-ws2013std",
    "W103-wsrawhbrtd", "W91-wsholo0grawtd", "W91-wsholo1grawtd", "W91-wsholo2grawtd",
    "W91-wsholo3grawtd", "W91-wsholo4grawtd", "W91-wsholo5grawtd", "W91-wshologmrawtd",
    "S14-ws2011std", "S21-ws2012std", "W41-ws2015wtd", "S61-wsrawimltdp",
    "S07-ws2009std", "W115-rawimascgntcutetd", "S110-wsrawimasscstd", "S81-imassctd",
    "W13-ws2011wtd", "S88-wsddmrawtd", "W44-ws2016wtd", "S66-wsrawjjgwtd",
    "W62-wsrawsneakertdp", "W123-rawsneaker2td", "S79-wsrawloveiswartd", "S123-wsrawkj8td",
    "S67-wstrawkantaitdp", "S25-ws2014std", "W51-wsrawkmntdp", "S27-ws2014std",
    "S05-ws2009std", "W133-wsrawkin15td", "S44-ws2016std", "W49-ws2017wtd",
    "W116-wsrawyurutd", "W21-ws2012wtd", "W06-ws2009wtd", "W02-ws2008wtd",
    "SE20-ws2014std", "S74-wsrawlostdtdp", "W122-rawlinkliketd", "W85-wsrawlnjtd",
    "W36-ws2015wtd", "W53-wsrawllstdp", "W45-ws2016wtd", "W92-wsllsprawtd",
    "W24-ws2013wtd", "W05-ws2009wtd", "W105-wsrawlycotd", "S13-ws2011std",
    "W80-wsrawmmratdp", "W59-rawwsmrecotdp", "W17-ws2012wtd", "W126-wsrawmakeinetd",
    "S89-wsmrvlrawtd", "S10-ws2010std", "S19-ws2012std", "S33-ws2015std",
    "S11-ws2010std", "W96-wsdragonmaidtdraw", "S83-wsmushokurawtd", "W12-ws2010wtd",
    "W12-ws2011wtd", "W04-ws2008wtd", "S117-rawnikketd", "W30-ws2014wtd",
    "S58-wsrawngltdp", "S107-wsrawoshinktd", "S41-ws2016std", "S62-wsrawoverlordtdp",
    "S01-ws2008std", "SE12-ws2012std", "S08-ws2009std", "S45-ws2016std",
    "W07-ws2009wtd", "W84-wsrawpriconnetd", "S91-wssekailntdraw", "S38-ws2016std",
    "S105-wsrawpadtd", "W83-wsrawqqichikatd", "W83-rawqqitsukitd", "W83-wsrawqqmikutd",
    "W83-wsrawqqninotd", "W83-rawqqyotsubatd", "W26-ws2013wtd", "W10-ws2010wtd",
    "W64-wsrawrascaltdp", "S46-ws2016std", "W86-wsrawkanokaritd", "S56-wsrawrevuetd",
    "W15-ws2011wtd", "W16-ws2012wtd", "S115-wsrawkenshintd", "W56-wsrawsaekanotdp",
    "S73-wsrawsssttdp", "S37-ws2015std", "S06-ws2009std", "W14-ws2011wtd",
    "S04-ws2008std", "S106-wsrawspytd", "S49-wsrawstartd", "S60-wsrawstgtdp",
    "W60-wssmptdp", "SE23-ws2014std", "S65-wsrawsaoalztdp", "S59-rawsaoaggtd",
    "S20-ws2012std", "W19-ws2012wtd", "S126-wsrawtalestd", "S32-ws2014std",
    "S70-wsrawtimeslimetdp", "W87-wsdaygodtd", "WE13-ws2012wtd", "W03-ws2008wtd",
    "S72-wsgrisrawtd", "W37-ws2015wtd", "S92-wsrevengerstdraw", "S130-wsrawtouhoutd",
    "W121-rawamagamitd", "W106-wsrawuma1rtd", "W50-ws2017wtd", "W22-ws2013wtd",
    "S85-wswtrawtd", "W111-wsrawyohanetd", "W61-wsrawyhhtdp", "W93-wszlsrrawtd",
    "W138-wsrawanetd",
    # Booster packs
    "wsaccelbp", "wsawibbp", "wsalicegearbp", "wsabnkwbp", "wsabrebp", "wsaogiribp",
    "wsarifuretabp", "wsallbp", "wsalilylbbp", "wsalily2bp", "wsaotbp", "wsaotv2bp",
    "wsayakashivbp", "wsazurlanebp", "wsazur2bp", "wsbakebp", "wsbdgbp5thbp",
    "wsbdgbpbp", "wsbdgbpv2bp", "wsbdgoxavebp", "wsbdbp", "wsbdv2bp",
    "wsbluearchivebp", "wsblueanibp", "wsbtrbp", "wsbofuribp", "wsccs25bp",
    "wsccsccbp", "wschainccbp", "wschainsawbp", "wschabp", "wscircusbp",
    "wscrayonbp", "wscscmvbp", "wsd4djgmbp", "wsdcidetbp", "wsdcdc2bp",
    "wsdcdc2pcbp", "wsdc10thbp", "wsdc3bp", "wsdcwydsbp", "wsdcretunebp",
    "wsdandadanbp", "wsdandadan2bp", "wsdarlingbp", "wsdatealivebp", "wsdal2bp",
    "wsdal3bp", "wsdbibp", "wsdengekibp", "wsdisgaeabp", "wsdisney100bp",
    "wsevabp", "wsft100bp", "wsftbp", "wsfateapobp", "wsfategobp", "wsfgocbp",
    "wsfpizhbp", "wsfsnbp", "wsfsnhf2bp", "fsnubwbp", "wsfubw2bp", "wsfatezerobp",
    "wsfsnhfbp", "wsfrierenbp", "wsfrierennebp", "wsfantasiabp", "wsfujimi2bp",
    "wsgakumasbp", "wsgargantiabp", "wsgfbbp", "wsgfbv2bp", "wsgoblinbp",
    "wsguiltybp", "wsgurrenbp", "wsharuhibp", "wsmiku2bp", "wsmikubp",
    "wsheavenbrbp", "wshbr2bp", "wshololivebp", "wshololivev2bp", "wsimas2bp",
    "wsimasabp", "wsimasbp", "wsimcg2bp", "wsimcbp", "wsimasmlbp", "wsimasmlnsbp",
    "wsimasmbp", "wsimascgntbp", "wsimasscbp", "wsimasscsmbp", "wsi1rbp", "wsi2rbp",
    "wsdanmachibp", "wsrabbitrebp", "wsrabbitsbloombp", "wsrabbitbp", "wsrabbitsdmsbp",
    "wsjojogwbp", "wssneakerbp", "wssneaker2bp", "wsloveiswarbp", "wskaguya2bp",
    "wskaiju8bp", "wskancollebp", "wskc5thbp", "wskceubp", "wskc2bp", "wskemonobp",
    "wskey20bp", "wskeyallstarbp", "wsklkbp", "wskofbp", "wskinmoza15bp", "wskizbp",
    "wskonosuba2bp", "wskonosubabp", "wskonosubarebp", "wskonosubalcbp", "wsyurucampbp",
    "wslbanimebp", "wslbbp", "wslbxtcbp", "wslostdbp", "wslinklikellbp", "wsllnjv2bp",
    "wsllnijibp", "wslovelivebp", "wsllsif2mlbp", "wslovelivesifbp", "wwllsifv2bp",
    "wsllsifv3bp", "wslssbp", "wslsssifbp", "wslssv2bp", "wsllsstarbp", "wsllv2bp",
    "wsluckystarbp", "wslycorecobp", "wsmacrossbp", "wsmmrabp", "wsmrecobp",
    "wsmmbp", "wsmrbp", "wsmakeinebp", "wsmarvelbp", "wsmeltybp", "wsmilky2bp",
    "wsmilkybp", "wsmhssbp", "wsdragonmaidbp", "wsmsssbp", "wsmushokubp",
    "wsnanoabp", "wsnanodbp", "wsnanorbp", "wsnanosbp", "wsnano2abp", "wsn12abp",
    "wsnikkebp", "wsnkoibp", "wsnisemonobp", "wsngnlbp", "wsoshinokobp", "wsosk2bp",
    "wsosobp", "wsoverlordbp", "wsoverlord2bp", "wsp3bp", "wsp4bp", "wsp5bp",
    "wsphantombp", "wspriconnebp", "wspriconnerd2bp", "wspjsekaibp", "wspjsk2bp",
    "wsproseka3bp", "wspybp", "wspadbp", "wsquintsbp", "wsquintsmvbp", "wsquintsssbp",
    "wsrailsbp", "wsaobutabp", "wsrascalscbp", "wsaobutambp", "wsbutasbp",
    "wsrezerobp", "wsrezeromsbp", "wsrezerov2bp", "wsrezero3bp", "wskanokaribp",
    "wsrentav2bp", "wsrevuebp", "wsrslmoviebp", "wsrslrelivebp", "wsrewriteabp",
    "wsrewritebp", "wsrewritehfbp", "wsrobonotesbp", "wskenshinbp", "wssaekanobp",
    "wssaekanofinebp", "wssaekanofbp", "wssakurawarsbp", "wssgsbp", "wsbasarabp",
    "wsshanabp", "wsexabp", "wsspyfamilybp", "wsstarwarsbp", "wsstgbp",
    "wssumpokanibp", "wssmpbp", "wssummerrbbp", "wssao10thbp", "wssaoalzbp",
    "wssaoa2bp", "wssaoaggobp", "wssaoa10bp", "wssaobp", "wssaoosbp", "wssaorebp",
    "wssao2bp", "wssymaxzbp", "wssymbp", "wssymgbp", "wssymgxbp", "wssymxdubp",
    "wssymxduxbp", "wssymxvbp", "wstalesofbp", "wsterrabp", "wstimeslimebp",
    "wsslimev2bp", "wstimeslimev3bp", "wsdaygodbp", "wsfamzerobp", "wsfgrisaiabp",
    "wsgrisaia2bp", "wsgrisptbp", "wstlrd2bp", "wstlrd2v2bp", "wstrevengersbp",
    "wstouhoubp", "wsamagamibp", "wsumamusumebp", "wsumamvbp", "wsumacgbp",
    "wsvividstbp", "wsvividbp", "wswtriggerbp", "wsyohanebp", "wsyuunabp", "wszlsrbp",
    # Extra boosters / extras
    "wsangelbeb", "wsangelb2eb", "wsbdmxraseb", "wsbdppreb", "wsbrseb", "wscanaaneb",
    "wscl1eb", "wscl2eb", "wscl3eb", "wsdcdc2eb", "wsdcdc2pceb", "wsdc2ebep",
    "wsdc3aeb", "wsdcsseb", "wsdcvslbeb", "wsdabeb", "wsds2eb", "wsdis4eb",
    "wsdisd2eb", "wsdogdaysdasheb", "wsdogdaysddeb", "wsdogdayseb", "wsftaileb",
    "wsfatezeroeb", "wsfhaeb", "wsfatepideb", "wsfatepieb", "wsfateklpippeb",
    "wsfpizeb", "wsgsteb", "wsgzleb", "wsharuhieb", "wsmikuxeb", "wshinavol1eb",
    "wshinavol2eb", "wsimasdseb", "wsimmcp765eb", "wsrabbiteb", "wskcabysseb",
    "wskgeb", "wslbcmeb", "wslbexeb", "wslbrefraineb", "wslogeb", "wslleb",
    "wslsseb", "wsllmveb", "wsmilkyg4eb", "wsmhsbeb", "wsmilkypteb", "wsnanom1eb",
    "wsnichijoueb", "wsnkeb", "wsp4eb", "wsp4aeb", "wsp4ueb", "wspqeb",
    "wspsychoeb", "wsrzfbeb", "wsrineb", "wsbasaraaeb", "wsshanafinaleb", "wssreb",
    "wssaoggo2eb", "wssao2eb", "wssaoiiv2eb", "wsfamzerofeb", "wsmai1eb", "wsmai2eb",
    "wsvgaweeb", "wswooserep",
    # Premium / misc
    "wsalllbtpb", "wsbd10pb", "wsbd5thid", "wsbdgbpccpb", "wsbdgrppb", "wsbdgbpsp",
    "wsbdkkcc", "wwcgsss", "wsclps", "wsdc20pb", "wsdogdayset", "wsgbcpb",
    "wsharuhips", "wsholoambset", "wsholopb", "wsholosummerpb", "wsimasmlpb",
    "wsimasps", "wsimas765pb", "wsimascgpb", "wsimasscpb", "wsgochiusa10pb",
    "wskget", "wskey25pb", "wsklkps", "wskofpb", "wslhps", "wsllsif10apb",
    "wslovelive9sif", "wsllthankspb", "wsllsifvs", "wsllsmds", "wslycorecopb",
    "wsmacdeltapb", "wsmhffpp", "wsmilkysc", "wsnano20pb", "wsoverlordmveb",
    "wsp3rpb", "wsqqinpb", "wsrailsps", "wsrsekaieb", "wsrevueedelpb", "wsspromo",
    "wsshanapb", "wswspromo", "wswpromo",
]

session = requests.Session()
session.headers["User-Agent"] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

def load_manifest():
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)

def find_trans_url_from_cardlist(set_id):
    """Hit the cardlist page and scrape out the /translations/ link."""
    url = f"{BASE}/code/cardlist.html?pagetype=ws&cardset={set_id}"
    try:
        r = session.get(url, timeout=15, allow_redirects=True)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/translations/" in href and href.endswith(".html"):
                return BASE + href if href.startswith("/") else href
    except Exception:
        pass
    return None

def fetch_url(url, retries=1):
    for attempt in range(retries + 1):
        try:
            r = session.get(url, timeout=20, allow_redirects=True)
            if r.status_code == 200:
                # Check it's not the rate-limit page
                if "open a bunch of pages" in r.text:
                    print(f"  [rate-limited] sleeping 10s...")
                    time.sleep(10)
                    continue
                return r.text
            elif r.status_code in (301, 302):
                print(f"  [redirect] {url}")
                return None
            else:
                print(f"  [HTTP {r.status_code}] {url}")
                return None
        except Exception as e:
            print(f"  [error] {e}")
        time.sleep(2)
    return None

def crawl():
    os.makedirs(HTML_DIR, exist_ok=True)
    manifest = load_manifest()

    # Build lookup: set_id → translation url from manifest
    url_map = {}
    for set_id, info in manifest.items():
        url = info.get("translation_url") or info.get("candidate_url")
        if url:
            url_map[set_id] = url

    existing = {f[:-5] for f in os.listdir(HTML_DIR) if f.endswith(".html")}

    to_fetch = [s for s in SITE_SETS if s not in existing]
    print(f"Already have: {len(existing)}  |  To fetch: {len(to_fetch)}")

    ok = fail = skipped_no_url = 0

    for i, set_id in enumerate(to_fetch, 1):
        out_path = os.path.join(HTML_DIR, f"{set_id}.html")

        trans_url = url_map.get(set_id)

        if not trans_url:
            # Try to discover from cardlist page
            print(f"[{i}/{len(to_fetch)}] {set_id} — discovering URL...")
            trans_url = find_trans_url_from_cardlist(set_id)
            time.sleep(DELAY)
            if not trans_url:
                print(f"  [no-url] {set_id}")
                skipped_no_url += 1
                continue

        print(f"[{i}/{len(to_fetch)}] {set_id} -> {trans_url}")
        html = fetch_url(trans_url)
        time.sleep(DELAY)

        if html:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(html)
            ok += 1
        else:
            fail += 1

    print(f"\nDone: {ok} saved, {fail} errors, {skipped_no_url} no-url")

if __name__ == "__main__":
    crawl()
