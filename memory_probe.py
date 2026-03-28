import json

def main():
    try:
        with open("/home/frost/.gemini/memory/events.jsonl", "r") as f:
            lines = f.readlines()
            last_five = lines[-5:]
            for line in last_five:
                try:
                    event = json.loads(line)
                    print(f"Timestamp: {event['timestamp']}, Event Type: {event['event_type']}")
                except json.JSONDecodeError:
                    print(f"Error decoding JSON: {line.strip()}")
                except KeyError:
                    print(f"Missing key in event: {line.strip()}")

    except FileNotFoundError:
        print("Error: Memory file not found.")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()