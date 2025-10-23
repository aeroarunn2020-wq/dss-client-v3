import json
import os

CONFIG_FILE = "client_config.json"

def configure_algorithm():
    """Asks the user for their preferred mining algorithm and saves it."""
    print("--- Configure Mining Client ---")
    print("Please select your preferred mining algorithm.")
    print("This allows the client to only work on jobs for specific hardware (e.g., CPU for RandomX, GPU for KawPow).")
    
    print("\n[1] RandomX (Best for CPUs)")
    print("[2] KawPow (Best for GPUs)")
    print("[3] Both (Will mine whichever job the pool sends)")
    
    while True:
        choice = input("\nEnter your choice (1, 2, or 3): ")
        if choice == '1':
            preference = 'randomx'
            break
        elif choice == '2':
            preference = 'kawpow'
            break
        elif choice == '3':
            preference = 'both'
            break
        else:
            print("Invalid choice. Please enter 1, 2, or 3.")
            
    config_data = {"algorithm_preference": preference}
    
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config_data, f, indent=4)
        print(f"\nConfiguration saved successfully! Client is set to mine: {preference.upper()}")
        print(f"You can now run clientV2.py.")
    except Exception as e:
        print(f"\nError: Could not save configuration to '{CONFIG_FILE}'. Details: {e}")

if __name__ == '__main__':
    configure_algorithm()
