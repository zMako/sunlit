import sys; sys.path.insert(0, "/Users/maciejkopiec/sunlit/app/furnish/designer")
from common import *
B = "louis-poulsen"
def main():
    sm = get("https://www.louispoulsen.com/en/commercesitemap.xml", cache=cpath(B, "sm", "xml"))
    urls = re.findall(r"<loc>([^<]+)</loc>", sm.text)
    for t in ("fbx",):
        get(f"https://commerce.louispoulsen.com/api/downloadcenter/list?type={t}&locale=en", cache=cpath(B, "list-"+t, "json"))
    get("https://commerce.louispoulsen.com/api/downloadcenter/products?locale=en", cache=cpath(B, "dcprods", "json"))
    for i, u in enumerate(urls):
        if u.count("/") < 6 or "spare-parts" in u: continue
        get(u, cache=cpath(B, u)); 
        if i % 20 == 0: print(i, len(urls), flush=True)
main()
