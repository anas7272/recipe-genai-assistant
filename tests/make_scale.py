"""Synthetic dataset (~N recipes) in the real file format, only for performance testing.  python tests/make_scale.py out_dir 120000"""
import json, os, random, sys
random.seed(1)
ING = ["2 large eggs, beaten","1 cup all-purpose flour","3/4 cup sugar","1/2 cup butter, softened","1 cup milk","2 cloves garlic, minced","1 onion, chopped",
 "2 tablespoons olive oil","salt and freshly ground black pepper","1 (14 ounce) can diced tomatoes","1 pound penne pasta","1 cup heavy cream","1/2 cup grated Parmesan cheese",
 "2 cups cooked rice","1 teaspoon baking powder","1 teaspoon vanilla extract","3 ripe bananas, mashed","1/4 cup applesauce","4 chicken breasts","1 cup chicken broth",
 "1 tablespoon soy sauce","2 carrots, sliced","1 cup shredded cheddar cheese","1/2 cup peanut butter","1 egg or 1/4 cup applesauce","1 red bell pepper","1/2 cup sour cream",
 "2 tablespoons chopped fresh parsley","1 teaspoon cumin","1 cup spinach","1/4 cup coconut milk","1 eggplant","8 ounces mushrooms","1 cup water","1 lemon, juiced","1 teaspoon paprika"]
TITLES = ["Banana Bread","Chicken Soup","Penne Bake","Tomato Pasta","Fried Rice","Pound Cake","Veggie Stir Fry","Cream Sauce Pasta","Spinach Casserole","Garlic Chicken"]
def rec(i):
    n = random.randint(4, 14)
    return {"title": f"{random.choice(TITLES)} {i}", "ingredients": random.sample(ING, n) + (["ADVERTISEMENT"] if i % 7 == 0 else []),
            "instructions": "\n".join(f"Step {j} does something with the food." for j in range(random.randint(2, 12))), "picture_link": None}
out, N = sys.argv[1], int(sys.argv[2])
os.makedirs(out, exist_ok=True)
for k, s in enumerate(("ar", "epi", "fn")):
    json.dump({f"{s}{i}": rec(i) for i in range(N // 3)}, open(f"{out}/recipes_raw_nosource_{s}.json", "w"))
