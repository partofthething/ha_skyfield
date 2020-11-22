/* A card for the skyfield integration.
 *
 * I think perhaps we need to update the skyfield backend
 * to produce the data as a state variable, including the line
 * for the solstices and all the planets. Then we can just grab
 * that state through the state machine.
*/
class SkyfieldCard extends HTMLElement {
  set hass(hass) {
    if (!this.content) {
      const card = document.createElement('ha-card');
      var plotly = document.createElement('script');
      plotly.setAttribute('src','https://cdn.plot.ly/plotly-latest.min.js');
      document.head.appendChild(plotly);
      card.header = 'Skyfield';
      this.content = document.createElement('div');
      this.content.style.padding = '0 16px 16px';
      card.appendChild(this.content);
      this.appendChild(card);
    }

    const entityId = this.config.entity;
    const state = hass.states[entityId];
    const stateStr = state ? state.state : 'unavailable';

    //this.content.innerHTML = `
    //  The state of ${entityId} is ${stateStr}!
    //  <br><br>
    //  <img src="http://via.placeholder.com/350x150">
    //`;
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error('You need to define an entity');
    }
    this.config = config;
  }

  // The height of your card. Home Assistant uses this to automatically
  // distribute all cards over the available columns.
  getCardSize() {
    return 3;
  }

  makePlot() {
    var data = {
        r: [1,2,3,4,5,6],
        theta: [10,20,45,90,180,270],
        mode: 'lines',
        name: 'My data',
        marker: {
          color: 'none',
          line: {color: 'green'}
        },
        type: 'scatterpolar'
    };

    var layout = {
      title: 'Space status',
      font: {
        family: 'Arial, sans-serif;',
        size: 12,
        color: '#000'
      },
      showlegend: true,
      orientation: -90
    };
    Plotly.newPlot('content', [data], layout);
    }
  }
}

customElements.define('skyfield-card', SkyfieldCard);
