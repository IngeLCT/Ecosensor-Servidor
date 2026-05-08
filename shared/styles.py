from nicegui import ui


def add_styles() -> None:
    ui.add_head_html(
        '''
        <style>
        body { 
            margin: 0;
            padding: 0;
            width: 100%;
            height: 100%;
            overflow: hidden;
            background: #cce5dc; 
            color: #101820; 
            }
        .connect-shell {
        width: 100%;
        min-height: 100dvh;
        box-sizing: border-box;
    
        display: flex;
        align-items: center;
        justify-content: center;
    
        padding: 20px;
        overflow: hidden;
        }
        .connect-card {
            width: min(560px, 100%);
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 15px;
            text-align: center;
        }
        .connect-title {
            color: #045709;
            font-size: 34px;
            font-weight: 700;
            line-height: 1.1;
        }
        .connect-logo {
            width: 150px !important;
            height: 150px !important;
            max-width: 150px;
            max-height: 150px;
            overflow: visible;
        }
        
        .connect-logo img,
        .connect-logo .q-img__image {
            object-fit: contain !important;
            background-size: contain !important;
            background-repeat: no-repeat !important;
            background-position: center !important;
        }
        .connect-subtitle {
            color: #000;
            font-size: 26px;
            font-weight: 700;
            text-decoration: underline;
            line-height: 1.1;
        }
        .connect-box {
            width: min(460px, 100%);
            display: flex;
            flex-direction: column;
            gap: 12px;
            align-items: stretch;
        }
        .connect-label {
            font-size: 17px;
            font-weight: 700;
            color: #101820;
            text-align: left;
        }
        .connect-input .q-field__control { background: #fff; }
        .connect-button { background: #214e78 !important; color: #fff !important; }
        .dashboard {
            width: min(1180px, 100%);
            margin: 0 auto;
            padding: 28px 18px 44px;
            text-align: center;
            font-family: "Arial Narrow", Arial, sans-serif;
        }
        .top-nav {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 10px 18px;
            margin-bottom: 18px;
            font-size: 18px;
            font-weight: 700;
        }
        .brand-title { color: rgb(4, 87, 9); font-size: 28px; font-weight: 700; }
        .section-title {
            color: rgb(4, 4, 52);
            font-size: 26px;
            font-weight: 700;
            text-decoration: underline;
        }
        .pollutant-card {
            background: rgba(255, 255, 255, .52);
            border: 1px solid rgba(0, 0, 0, .12);
            border-radius: 8px;
            padding: 16px;
        }
        .thumbs {
            display: grid;
            grid-template-columns: repeat(4, minmax(110px, 1fr));
            gap: 12px;
        }
        .thumb {
            background: #fff;
            border: 1px solid rgba(0, 0, 0, .14);
            border-radius: 8px;
            padding: 8px;
            font-weight: 700;
        }
        .thumb img {
            width: 100%;
            height: 84px;
            object-fit: contain;
        }
        .measure-table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            margin-top: 20px;
        }
        .measure-table th,
        .measure-table td {
            font-size: 24px;
            text-align: center;
            border: 1px solid black;
            padding: 10px;
        }
        .measure-table th { background: #80ffd4; }
        .status-line {
            min-height: 28px;
            font-size: 19px;
            color: #1d332a;
        }
        @media (max-width: 760px) {
            .connect-title { font-size: 30px; }
            .connect-logo { width: 104px; height: 104px; }
            .connect-subtitle { font-size: 23px; }
            .thumbs { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
            .measure-table th,
            .measure-table td { font-size: 18px; }
        }
        </style>
        '''
    )
