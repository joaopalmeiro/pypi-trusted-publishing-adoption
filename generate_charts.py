import pandas as pd

if __name__ == "__main__":
    results_df = pd.read_csv("results.csv")
    print(results_df.head())
