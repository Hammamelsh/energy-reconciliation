const REPO = "https://github.com/Hammamelsh/energy-reconciliation";

export function Footer({ notice }: { notice: string }) {
  return (
    <footer>
      <div className="wrap cols">
        <div>
          <h3>Energy Reconciliation</h3>
          <p style={{ margin: 0 }}>
            Half-hourly smart-meter readings from the Low Carbon London trial, taken from the raw archive to a tested,
            versioned tariff calculation, with every figure traceable to the rows and the assumption it rests on.
          </p>
          <p style={{ marginBottom: 0 }}>{notice}</p>
        </div>
        <div>
          <h3>Go deeper</h3>
          <ul>
            <li><a href={REPO}>Source code and write-ups on GitHub</a></li>
            <li><a href={`${REPO}/blob/main/docs/anl-005-flat-price-comparison.md`}>The comparison, household by household</a></li>
            <li><a href={`${REPO}/blob/main/docs/anl-004-zero-days.md`}>Whole days of zero</a></li>
            <li><a href={`${REPO}/blob/main/docs/fore-001-forecasting-experiment.md`}>The forecasting backtest</a></li>
          </ul>
        </div>
        <div>
          <h3>Deep explorer</h3>
          <p style={{ margin: 0 }}>
            The Streamlit explorer walks every household's readings, data quality and forecast; it runs on the full
            sealed database. Hosting it is pending; the <a href={`${REPO}/blob/main/docs/publication-workflow.md`}>guide</a>{" "}
            shows how to run it locally in one command.
          </p>
        </div>
      </div>
    </footer>
  );
}
