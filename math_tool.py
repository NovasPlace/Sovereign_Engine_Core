
import sys

def main():
  if len(sys.argv) != 3:
    print("Usage: python math_tool.py <num1> <num2>")
    sys.exit(1)

  try:
    num1 = float(sys.argv[1])
    num2 = float(sys.argv[2])
  except ValueError:
    print("Error: Both arguments must be numbers.")
    sys.exit(1)

  result = num1 * num2
  print(result)

if __name__ == "__main__":
  main()
