import json

def read_memory_events(filepath="/home/frost/.gemini/memory/events.jsonl", num_events=5):
    try:
        with open(filepath, "r") as f:
            lines = f.readlines()
            last_events = lines[-num_events:]

            for line in last_events:
                try:
                    event = json.loads(line)
                    timestamp = event.get('ts') or event.get('timestamp') or 'Timestamp not found'
                    event_type = event.get('type') or event.get('event_type') or 'Event type not found'

                    print(f"Timestamp: {timestamp}, Event Type: {event_type}")

                except json.JSONDecodeError:
                    print(f"Error decoding JSON: {line.strip()}")

    except FileNotFoundError:
        print(f"Error: File not found at {filepath}")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    read_memory_events()