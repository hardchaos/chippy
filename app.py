# Chippy v1.0
# By hardchaos (Adam Kahn)
# https://github.com/hardchaos/chippy
# Released under the MIT License

import discord
import openai
import requests
import sqlite3
import time
import keyway

# ENVIRONMENT SETTINGS 
BOT_NAME = "Chippy"

# allow image generation
ALLOW_IMAGES = False # this can be dangerous to your wallet
IMAGE_SIZE = 1024 # can be 256, 512, or 1024
IMAGE_PROMPT = "image of" # example message: @chippy image of a dog

# by default uses ChatGPT (with history)
CHAT_MODEL = "gpt-3.5-turbo"
CONTEXT_PROMPT = "you are" # allows setting context with first message
                           # example: @chippy you are a helpful assistant
DEFAULT_CONTEXT = "you are a helpful assistant." 
                           # set fallback context if user does not create one
STORE_LOCALLY = True # store messages locally in a sqlite database
                     # highly reccomended, recursively calling discord tends to get rate limited
DB_NAME = "CHIPPY" # for storing messages

# (deprecated) older text models (without history)
USE_TEXT_MODEL = False
TEXT_MODEL = "text-davinci-003"
TEXT_MAX_TOKENS = 2048

# enable debugging in server printout
DEBUG = False

# Keyway setup (for API keys)
kw = keyway.Keyway()
DISCORD_TOKEN = kw["DISCORD_TOKEN"]
OPENAI_KEY = kw["OPENAI_KEY"]


# SET UP ENVIRONMENT

# set up discord 
intents = discord.Intents.all()
client = discord.Client(intents = intents)

# set up openai
openai.api_key = OPENAI_KEY


# CLASSES

# this class represents a database connection
class Database:
    # instatiate self and create connection
    def __init__(self, database_name):
        self.database_name = database_name + ".db"
        self.conn = sqlite3.connect(self.database_name)
        self.cursor = self.conn.cursor()

    # close connection
    def close(self):
        self.conn.commit()
        self.conn.close()

# this class holds functions for storing messages in the database
class SqlUtils:
    
    def __init__():
        None
    
    # create "messages" table    
    async def create_database():
        db = Database(DB_NAME)
        db.cursor.execute("""
                    CREATE TABLE IF NOT EXISTS messages
                    (
                        message_id INTEGER PRIMARY KEY,
                        parent_id INTEGER,
                        role TEXT,
                        message TEXT
                    )
                    """)
        db.close()

    # drop messages table (unused)
    async def drop_table(table_name):
        db = Database(DB_NAME)
        db.cursor.execute(f"""DROP TABLE IF EXISTS {table_name}""")
        db.close()
        
    # insert a single message into messages
    async def enter_message(message_id, parent_id, role, message):
        message = message.replace('"',"'")
        db = Database(DB_NAME)
        db.cursor.execute(f"""INSERT OR REPLACE INTO messages 
                    (message_id, parent_id, role, message)
                    VALUES({message_id}, {parent_id}, "{role}", "{message}")
                    """)
        db.close()

    # get a single message from messages
    async def get_message(message_id):
        db = Database(DB_NAME)
        db.cursor.execute(f"""
                    SELECT * FROM messages 
                    WHERE message_id = {message_id}
                    """)
        response = db.cursor.fetchone()
        db.close()
        return response

    # get a thread of all parents from messages
    async def get_thread(message_id):
        messages = []
        
        # get info for self
        row = await SqlUtils.get_message(message_id)
        messages.append(row)
        
        # loop through parents
        while row[1] != None:
            message_id = row[1]
            row = await SqlUtils.get_message(message_id)
            messages.append(row)
        
        # return reversed (chronological) string
        return messages[::-1]
    

# COMPLETION FUNCTIONS (OpenAI API interfaces)

# returns chat completion (ChatGPT)
async def chat_completion(messages):
    response = openai.ChatCompletion.create(model = CHAT_MODEL, 
                                     messages = messages)
    return response["choices"][0]["message"]["content"]

# returns text completion (old model, deprecated)
def text_completion(message, max_tokens = 2048):
    response = openai.Completion.create(model = TEXT_MODEL,
                         prompt = message,
                         max_tokens = max_tokens)
    return response["choices"][0]["text"]

# returns a url of an image 
def image_completion(message, resolution = str(IMAGE_SIZE)):
    response = openai.Image.create(prompt=message,
                                    n=1,
                                    size=f"{resolution}x{resolution}",
                                    )
    return response["data"][0]["url"]

# saves an image from a url and returns the image as a file
async def get_image(prompt):

    # image prompt
    completion_url = image_completion(prompt)
    
    # format the filename to be the first 100 characters of the prompt
    filename = "".join([letter for letter in prompt.lower().replace(" ", "_") if letter.isalnum() or letter == '_'])[:100]
    
    # get and save image
    response = requests.get(completion_url)
    with open(f"images/{filename}.png", "wb") as f:
        f.write(response.content)
    
    
    with open(f"images/{filename}.png", "rb") as f:
        file = discord.File(f, filename=f"{filename}.png")
    
    return file


# DISCORD FUNCTIONS

# strip @chippy out of the initial message
async def message_to_prompt(message):
    # look for user tag
    if message.content.strip().startswith("<") and ">" in message.content:
        # strip first user out
        prompt = message.content[message.content.index(">")+1:].strip()
    else:
        # return original message
        prompt = message.content
    return prompt

# get a message's parent from discord 
async def get_parent_discord(message):
    # check to see if message has a parent
    if message.reference is not None:
        # Retrieve the parent message using the reference
        parent = await message.channel.fetch_message(message.reference.message_id)
    else:
        parent = None
    return parent

# get parents from local sqlite database
async def get_parents_locally(message):
    
    # get thread
    thread = await SqlUtils.get_thread(message.id)
    
    if thread:
        # format thread as messages for OpenAI
        messages = [{"role": i[2], "content": i[3]} for i in thread]
        return messages
    else:
        return []
    
# get all the parent messages by recursively calling discord (deprecated)
async def get_parents_discord(message):
    parents = []
    current_message = message

    # loop while there still exist parents
    while current_message.reference is not None:
        # Retrieve the parent message using the reference
        parent_message = await get_parent_discord(current_message)

        # Add the parent message to the list
        parents.append(parent_message)

        # Traverse up the message tree
        current_message = parent_message
        
        # prevent getting rate limited
        time.sleep(10/1000)

    # reverse order for the formatter
    parents = parents[::-1]
    parents.append(message)
    return parents

# format the discord messages for ChatGPT API (deprecated)
async def format_parents_discord(messages):
    messages_output = []
    
    # loop through messages and format for OpenAI API
    for m in messages:
        
        prompt = await message_to_prompt(m)
        
        if m.author.name.lower() == BOT_NAME.lower():
            role = "assistant"
        else:
            role = "user"
            
        messages_output.append({"role": role, "content": prompt})
    
    # check to see if there is a user-set context
    if messages_output[0]["role"].lower() is not "system":
        messages_output = [{"role": "system", "content": DEFAULT_CONTEXT}] + messages_output

    if DEBUG:
        for m in messages_output:
            print(m)

    return messages_output

# traverse the tree up to the original parent
async def get_thread(message):
    if STORE_LOCALLY:
        return await get_parents_locally(message)
    else:
        parents = await get_parents_discord(message)
        return await format_parents_discord(parents)

# store message in local database
async def store_locally(message):
    
    # save " as "" for storing in Sqlite
    message.content = message.content.replace('"',"'")
    
    # local variables
    author = message.author
    reference = message.reference
    prompt = await message_to_prompt(message)
    
    # if no parent, set to NULL (Sqlite's version of None)
    if reference is None:
        reference = 'NULL'
    else:
        reference = message.reference.message_id
        
    # if message is context-setting set role as "system"
    if prompt.lower().startswith("you are"):
        author = "system"
        
    # if bot sent message set role as "assistant"
    elif message.author == client.user:
        author = "assistant"
    
    # if user sent message set role as "user"
    else:
        author = "user"
    
    if DEBUG:
        print(message.id, message.reference, message.author, prompt)
    
    # wait for the entry to be entered into sqlite
    await SqlUtils.enter_message(message.id, 
                                    reference, 
                                    author, 
                                    prompt)
    
    
# DISCORD BOT FUNCTIONS

# standard discord bot startup function
@client.event
async def on_ready():
    print(f"{client.user.display_name} is online")
    await SqlUtils.create_database()
    # set default context
    await SqlUtils.enter_message(0,'NULL',"system", DEFAULT_CONTEXT)
    
# on message event
@client.event
async def on_message(message):
    
    # get prompt from message
    prompt = await message_to_prompt(message)
    
    # test to see if bot is mentioned (for images)
    if client.user in message.mentions:
        
        # see if images are enabled
        if prompt.lower().startswith(IMAGE_PROMPT) and ALLOW_IMAGES:
            # get image
            file = await get_image(prompt)
            # send message
            await message.reply(prompt, file=file)
            return
        if STORE_LOCALLY:
            # see if message is setting a context
            if prompt.lower().startswith(CONTEXT_PROMPT):
                await SqlUtils.enter_message(message.id, 
                                                "NULL",
                                                "system",
                                                prompt)
                return
            # if not, set default context
            else:
                if message.reference is None:
                    await SqlUtils.enter_message(message.id, 
                                        0,
                                        "user",
                                        prompt)
                else:
                    await(store_locally(message))
                
    else:  
        #print("bot not mentioned")
        # check if local storage is enabled
        if STORE_LOCALLY:
            await store_locally(message)

    # break if bot sent message
    if message.author == client.user:
        return 
    
    # get thread
    messages = await get_thread(message)

    # if first message is a context message, reply to the thread
    if messages[0]["role"] == "system":
        # get completion
        #response = "test"
        response = await chat_completion(messages)
        # reply to the thread
        await message.reply(response)

    return

# run discord client    
client.run(DISCORD_TOKEN)

# TODO (Roadmap)
#   GPT-4 Support (multimodal features)
#   Per-server key management