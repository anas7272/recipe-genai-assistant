"""Tiny hand-written dataset in the real Recipe Box format, used for tests / the demo transcripts.
python tests/make_fixture.py tests/fixture"""
import json, os, sys

R = []
def add(src, key, title, ings, steps):
    R.append((src, key, title, ings, "\n".join(steps)))

add("epi","p1","Penne with Cream Sauce",["1 pound penne pasta","1 cup heavy cream","1/2 cup grated Parmesan","2 cloves garlic, minced","1 tablespoon butter","Salt and freshly ground black pepper","ADVERTISEMENT"],["Boil the penne until al dente.","Melt butter, saute garlic.","Add cream and Parmesan, simmer.","Toss with pasta."])
add("epi","p2","Penne Arrabbiata",["1 pound penne","1 (28 ounce) can crushed tomatoes","3 cloves garlic","1/2 teaspoon red pepper flakes","2 tablespoons olive oil","1/4 cup chopped fresh parsley","Salt"],["Cook penne.","Saute garlic and red pepper flakes in olive oil.","Add tomatoes and simmer 15 minutes.","Toss with pasta and parsley."])
add("ar","p3","Baked Penne with Coconut Milk and Spinach",["12 ounces penne pasta","1 cup coconut milk","2 cups fresh spinach","1 onion, diced","2 tablespoons olive oil","1 teaspoon salt"],["Cook penne.","Saute onion in oil.","Stir in spinach and coconut milk.","Combine with pasta and bake 20 minutes.","Serve warm."])
add("fn","p4","Penne alla Vodka",["1 pound penne","1/2 cup vodka","1 cup heavy cream","1 cup tomato sauce","1 onion","2 tablespoons butter","1/2 cup grated Parmigiano-Reggiano"],["Saute onion in butter.","Add vodka and cook off.","Add tomato sauce and cream.","Toss with penne and cheese."])
add("epi","t1","Quick Tomato Soup",["2 tablespoons olive oil","1 onion, chopped","2 cloves garlic","1 (28 ounce) can whole tomatoes","2 cups vegetable broth","Salt and pepper"],["Saute onion and garlic.","Add tomatoes and broth, simmer, then blend."])
add("epi","t2","Tomato Salad",["4 ripe tomatoes","1/4 red onion, sliced","2 tablespoons olive oil","1 tablespoon vinegar","Salt"],["Slice tomatoes.","Toss everything together."])
add("ar","t3","Shakshuka",["2 tablespoons olive oil","1 onion, chopped","1 red bell pepper","3 cloves garlic, minced","1 (28 ounce) can crushed tomatoes","1 teaspoon cumin","1 teaspoon paprika","4 eggs","Salt","Chopped parsley"],["Heat oil and saute onion and pepper.","Add garlic and spices.","Add tomatoes and simmer 10 minutes.","Make wells and crack in the eggs.","Cover and cook until the eggs set.","Garnish with parsley."])
add("fn","t4","Tomato Fried Rice",["2 cups cooked rice","2 eggs, beaten","3 tomatoes, chopped","1 onion, chopped","2 tablespoons vegetable oil","1 tablespoon soy sauce","Salt"],["Scramble eggs and set aside.","Fry onion and tomato.","Add rice, soy sauce and eggs; stir-fry.","Season and serve."])
add("fn","t5","Egg and Tomato Stir-Fry",["4 eggs","3 tomatoes","1 tablespoon oil","1 teaspoon sugar","Salt"],["Scramble eggs.","Cook tomatoes with sugar, add eggs back, serve."])
add("epi","t6","Spanish Rice",["1 cup rice","2 tomatoes","1 onion","2 tablespoons oil","2 cups water","Salt"],["Brown the rice in oil with onion.","Add tomatoes, water and salt.","Cover and cook until the rice is tender.","Fluff and serve."])
add("ar","t7","Peanut Noodles",["8 ounces spaghetti","1/2 cup peanut butter","2 tablespoons soy sauce","1 clove garlic","1 tablespoon sesame oil","1/4 cup chopped peanuts"],["Cook spaghetti.","Whisk sauce.","Toss together."])
add("epi","g1","Garlic Onion Chicken",["4 chicken breasts","4 cloves garlic","2 onions, sliced","2 tablespoons olive oil","Salt and pepper"],["Season chicken.","Brown chicken.","Add onion and garlic, cover and cook 20 minutes."])
add("epi","g2","Roasted Garlic Onion Soup",["2 heads garlic","3 onions","4 cups chicken broth","2 tablespoons butter"],["Roast garlic.","Cook onions in butter.","Add broth and garlic, simmer, blend.","Serve."])
add("fn","g3","Onion Rings",["2 onions","1 cup flour","1 egg","1 cup milk","Oil for frying","Salt"],["Slice onions.","Make batter.","Dip and fry until golden."])
add("fn","e1","Eggplant Parmesan",["2 eggplants","1 cup Reggiano cheese","2 cups tomato sauce","1 egg","1 cup breadcrumbs","Olive oil"],["Slice eggplants.","Dip in egg then breadcrumbs.","Fry.","Layer with sauce and cheese and bake."])
add("fn","e2","Veggie Stir Fry",["2 cups broccoli","1 carrot","1 tablespoon soy sauce","1 tablespoon oil","1 clove garlic"],["Heat oil.","Stir-fry vegetables with garlic.","Add soy sauce."])
add("ar","b1","Banana Bread",["3 ripe bananas, mashed","2 eggs","1/3 cup butter, melted","3/4 cup sugar","1 teaspoon baking soda","1 1/2 cups all-purpose flour","1 teaspoon vanilla extract","Pinch of salt"],["Preheat oven to 350 degrees.","Mash bananas and mix with butter.","Stir in sugar, eggs and vanilla.","Sprinkle baking soda and salt, then fold in flour.","Pour into a loaf pan.","Bake for 60 minutes."])
add("ar","b2","Vegan Banana Bread",["3 ripe bananas","1/4 cup applesauce","1/3 cup vegetable oil","3/4 cup sugar","1 teaspoon baking soda","1 1/2 cups flour","1 teaspoon cinnamon"],["Preheat oven.","Mash bananas, mix in oil and applesauce.","Stir in sugar then dry ingredients.","Bake 55 minutes."])
add("epi","b3","Eggless Banana Muffins",["2 bananas","1/4 cup applesauce","1/2 cup sugar","1 1/2 cups flour","1 teaspoon baking powder","1/4 cup oil"],["Mix wet ingredients.","Add dry.","Bake in muffin tin."])
add("epi","b4","Applesauce Spice Cake",["1 1/2 cups applesauce","2 cups flour","1 cup sugar","1/2 cup vegetable oil","1 teaspoon baking soda","1 teaspoon cinnamon"],["Mix.","Pour into pan.","Bake 40 minutes."])
add("fn","b5","Flax Egg Brownies",["1 tablespoon ground flaxseed","3 tablespoons water","1/2 cup cocoa powder","1 cup sugar","1/2 cup flour","1/2 cup vegetable oil"],["Stir flaxseed with water and let it sit 5 minutes.","Combine with remaining ingredients.","Bake."])
add("fn","b6","Zucchini Bread",["3 eggs or 3/4 cup applesauce","2 cups grated zucchini","3 cups flour","1 cup sugar","1 cup vegetable oil","1 teaspoon baking soda","1 teaspoon cinnamon"],["Beat eggs.","Mix in zucchini and oil.","Fold in dry ingredients.","Bake 60 minutes."])
add("epi","b7","Pumpkin Bread",["1 cup pumpkin","2 eggs or 1/2 cup applesauce","1 1/2 cups flour","1 cup sugar","1/2 cup oil","1 teaspoon cinnamon"],["Mix.","Bake."])
add("ar","pc1","Penn Cove Mussels with Salmon",["2 pounds mussels","1 cup white wine","1 tablespoon olive oil"],["Steam the mussels in wine.","Serve."])
add("ar","c1","Chicken Alfredo",["12 ounces fettuccine","1 cup heavy cream","1/2 cup butter","1 cup Parmesan cheese","2 chicken breasts"],["Cook pasta.","Make sauce from butter, cream and cheese.","Add chicken and pasta."])
add("ar","c2","Cashew Cream Pasta",["12 ounces penne","1 cup cashews, soaked","1 cup water","2 cloves garlic","2 tablespoons olive oil","1 tablespoon lemon juice"],["Blend cashews, water, garlic and lemon to a cream.","Toss with cooked pasta."])
add("epi","c3","Creamy Tomato Pasta with Coconut Cream",["1 pound pasta","1 cup coconut cream","1 cup tomato sauce","2 cloves garlic","1 tablespoon olive oil"],["Cook pasta.","Simmer sauce with coconut cream.","Toss."])
add("ar","x1","Plain Omelet",["3 eggs","1 tablespoon butter","Salt"],["Whisk eggs.","Cook in butter.","Fold and serve."])
add("fn","x2","Fried Rice with Egg",["2 cups cooked rice","2 eggs","1 onion","2 tablespoons oil","1 tablespoon soy sauce","Salt"],["Scramble eggs.","Fry onion.","Add rice and soy sauce.","Serve."])
add("ar","x3","Plain Omelet",["3 eggs","1 tablespoon butter","Salt"],["Whisk eggs.","Cook in butter.","Fold and serve."])
add("fn","bad1","",["1 cup rice"],["Cook."])
add("fn","x4","Peanut Butter Cookies",["1 cup peanut butter","1 cup sugar","1 egg","1 teaspoon baking soda"],["Mix.","Bake 10 minutes at 350 degrees."])

def write(out):
    os.makedirs(out, exist_ok=True)
    files = {"ar": {}, "epi": {}, "fn": {}}
    for src, key, title, ings, instr in R:
        files[src][key] = {"title": title, "ingredients": ings, "instructions": instr, "picture_link": None}
    names = {"ar": "recipes_raw_nosource_ar.json", "epi": "recipes_raw_nosource_epi.json", "fn": "recipes_raw_nosource_fn.json"}
    for s, d in files.items():
        json.dump(d, open(os.path.join(out, names[s]), "w", encoding="utf-8"))

if __name__ == "__main__":
    write(sys.argv[1] if len(sys.argv) > 1 else "tests/fixture")
